"""DataForSEO HTTP client: auth, retries, rate limiting, partial-failure
isolation, and verbatim raw-response persistence (kept separate from
normalized data)."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from .cache import ResponseCache
from .config import Config

logger = logging.getLogger(__name__)


class DataForSEOError(Exception):
    """Raised for unrecoverable transport / auth / server failures."""


class PartialFailure(Exception):
    """Raised when the API accepts the call but a task failed internally."""

    def __init__(self, message: str, code: int, body: dict):
        super().__init__(message)
        self.code = code
        self.body = body


class DataForSEOClient:
    ENDPOINT_TASK_LIST = {
        "keyword_overview",
        "keyword_suggestions",
        "related_keywords",
    }

    def __init__(self, config: Config, cache: ResponseCache) -> None:
        self.config = config
        self.cache = cache
        self.base_url = config.api.base_url.rstrip("/")
        self.timeout = config.api.timeout_seconds
        creds = config.creds
        token = base64.b64encode(
            f"{creds.login}:{creds.password}".encode("utf-8")
        ).decode("ascii")
        self._headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        }
        self._rl_lock = threading.Lock()
        self._rl_last = 0.0
        rpm = config.api.rate_limit.requests_per_minute
        self._rl_min_interval = 60.0 / max(rpm, 1)
        self.raw_dir = config.abs_path(config.paths.raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    def _throttle(self) -> None:
        with self._rl_lock:
            elapsed = time.time() - self._rl_last
            wait = self._rl_min_interval - elapsed
            if wait > 0:
                time.sleep(wait)
            self._rl_last = time.time()

    def _endpoint_path(self, endpoint_key: str) -> str:
        try:
            rel = self.config.endpoints[endpoint_key]
        except (KeyError, AttributeError) as exc:
            raise DataForSEOError(f"unknown endpoint '{endpoint_key}'") from exc
        return rel

    def _safe_segment(self, text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "call"

    def _store_raw(self, endpoint_key: str, payload: Any, body: dict) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:8]
        endpoint_dir = self.raw_dir / self._safe_segment(endpoint_key)
        endpoint_dir.mkdir(parents=True, exist_ok=True)
        path = endpoint_dir / f"{stamp}_{payload_hash}.json"
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(body, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.warning("failed to persist raw response: %s", exc)
        return str(path.relative_to(self.config.root))

    # ------------------------------------------------------------------ #
    def post(self, endpoint_key: str, task_payload: dict,
             *, store_raw: bool = True) -> dict:
        """POST a single task to a Live endpoint. Returns the full decoded
        response body. Raises DataForSEOError for unrecoverable failures and
        PartialFailure when the request was accepted but the inner task
        failed.
        """
        cached = self.cache.get(endpoint_key, task_payload)
        if cached is not None:
            logger.debug("cache hit %s", endpoint_key)
            return cached

        url = self.base_url + self._endpoint_path(endpoint_key)
        body_bytes = json.dumps([task_payload]).encode("utf-8")

        rcfg = self.config.api.retry
        attempt = 0
        while True:
            attempt += 1
            self._throttle()
            try:
                resp = requests.post(url, headers=self._headers, data=body_bytes,
                                     timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt > rcfg.max_attempts:
                    raise DataForSEOError(f"transport error: {exc}") from exc
                self._sleep_backoff(attempt)
                continue

            status = resp.status_code
            try:
                parsed = resp.json()
            except ValueError as exc:
                # malformed / non-JSON response -> retry a couple times then give up
                if attempt > rcfg.max_attempts:
                    raise DataForSEOError(
                        f"malformed non-JSON response (HTTP {status})"
                    ) from exc
                logger.warning("malformed response, retrying")
                self._sleep_backoff(attempt)
                continue

            api_code = parsed.get("status_code")
            if status == 401 or api_code == 40100:
                raise DataForSEOError("unauthorized - check DATAFORSEO_LOGIN/PASSWORD")
            if status in rcfg.retryable_status or api_code in rcfg.retryable_api_codes:
                if attempt <= rcfg.max_attempts:
                    self._sleep_backoff(attempt)
                    continue
                raise DataForSEOError(
                    f"retryable failure exhausted (HTTP {status}, api {api_code})"
                )

            if status != 200 or api_code != 20000:
                raise DataForSEOError(
                    f"API failure HTTP {status} api {api_code}: "
                    f"{parsed.get('status_message')}"
                )

            # Per-task failure isolation: overall 20000 but inner task errored.
            tasks = parsed.get("tasks") or []
            if tasks:
                task = tasks[0]
                tcode = task.get("status_code")
                if tcode != 20000:
                    raise PartialFailure(
                        f"task failed: {task.get('status_message')}",
                        code=tcode, body=parsed,
                    )

            self.cache.set(endpoint_key, task_payload, parsed)
            if store_raw:
                self._store_raw(endpoint_key, task_payload, parsed)
            return parsed

    def _sleep_backoff(self, attempt: int) -> None:
        base = self.config.api.retry.backoff_base_seconds
        ceiling = self.config.api.retry.backoff_max_seconds
        delay = min(ceiling, base * (2 ** (attempt - 1)))
        delay += random.uniform(0, delay * 0.25)  # jitter
        logger.info("retrying in %.1fs (attempt %d)", delay, attempt)
        time.sleep(delay)

    # ------------------------------------------------------------------ #
    # Higher-level helpers returning extracted, schema-stable results.
    # ------------------------------------------------------------------ #
    def keyword_overview(self, keywords: List[str]) -> List[dict]:
        """Return list of keyword_overview items for the given keywords.
        Keywords with no data are omitted from the result (partial failure
        isolation: the call still succeeds for the rest)."""
        payload = {
            "keywords": keywords,
            "location_name": self.config.search.location_name,
            "language_name": self.config.search.language_name,
        }
        parsed = self.post("keyword_overview", payload)
        tasks = parsed.get("tasks") or []
        if not tasks:
            return []
        result = tasks[0].get("result") or []
        items: List[dict] = []
        for block in result:
            items.extend(block.get("items") or [])
        return items

    def expand(self, seed: str) -> List[str]:
        """Expand a seed into related keywords via suggestions + related."""
        if not self.config.expansion.enabled:
            return [seed]
        out: List[str] = []
        seen = set()
        common = {
            "location_name": self.config.search.location_name,
            "language_name": self.config.search.language_name,
        }
        # suggestions
        try:
            parsed = self.post("keyword_suggestions",
                               {**common, "keyword": seed,
                                "limit": self.config.expansion.suggestions_limit})
            for kw in self._extract_keywords(parsed):
                if kw not in seen:
                    seen.add(kw)
                    out.append(kw)
        except (DataForSEOError, PartialFailure) as exc:
            logger.warning("suggestions failed for '%s': %s", seed, exc)
        # related
        try:
            parsed = self.post("related_keywords",
                               {**common, "keyword": seed,
                                "limit": self.config.expansion.related_limit,
                                "depth": self.config.expansion.related_depth})
            for kw in self._extract_keywords(parsed):
                if kw not in seen:
                    seen.add(kw)
                    out.append(kw)
        except (DataForSEOError, PartialFailure) as exc:
            logger.warning("related failed for '%s': %s", seed, exc)

        if seed not in seen:
            out.insert(0, seed)
        cap = self.config.expansion.max_keywords_per_seed
        return out[:cap] if cap > 0 else out

    @staticmethod
    def _extract_keywords(parsed: dict) -> List[str]:
        keywords: List[str] = []
        for task in parsed.get("tasks") or []:
            for block in task.get("result") or []:
                for item in block.get("items") or []:
                    kw = item.get("keyword") or item.get("key")
                    if kw:
                        keywords.append(kw)
        return keywords
