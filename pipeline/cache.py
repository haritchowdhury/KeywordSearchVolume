"""SQLite response cache. Keeps raw API responses out of normalized data."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional


class ResponseCache:
    def __init__(self, db_path: str | Path, ttl_seconds: int = 604800,
                 enabled: bool = True) -> None:
        self.db_path = Path(db_path)
        self.ttl_seconds = ttl_seconds
        self.enabled = enabled
        self._lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS response_cache (
                    cache_key   TEXT PRIMARY KEY,
                    endpoint    TEXT,
                    payload     TEXT,
                    created_at  REAL,
                    ttl_seconds INTEGER,
                    body        TEXT
                )
                """
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS ix_cache_endpoint "
                "ON response_cache(endpoint)"
            )

    @staticmethod
    def make_key(endpoint: str, payload: Any) -> str:
        payload_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()[:24]
        return f"{endpoint}:{digest}"

    def get(self, endpoint: str, payload: Any) -> Optional[dict]:
        if not self.enabled:
            return None
        key = self.make_key(endpoint, payload)
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT body, created_at, ttl_seconds FROM response_cache "
                "WHERE cache_key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        age = time.time() - row["created_at"]
        if age > row["ttl_seconds"]:
            return None  # stale -> treat as miss
        try:
            return json.loads(row["body"])
        except (ValueError, TypeError):
            return None

    def set(self, endpoint: str, payload: Any, body: dict) -> None:
        if not self.enabled:
            return
        key = self.make_key(endpoint, payload)
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO response_cache "
                "(cache_key, endpoint, payload, created_at, ttl_seconds, body) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (key, endpoint, json.dumps(payload, sort_keys=True), time.time(),
                 self.ttl_seconds, json.dumps(body)),
            )

    def clear(self) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM response_cache")
