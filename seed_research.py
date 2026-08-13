"""Rank broad keyword seed phrases with one tool-free OpenAI API request.

The scores are model-inferred market judgments, not live search-volume or
Google Trends measurements. Nothing is saved; results are printed to stdout.

Examples:
    python3 seed_research.py  # uses run.seeds from config.yaml
    python3 seed_research.py "women's clothing" streetwear activewear
    python3 seed_research.py --count 40 --market "United Kingdom"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
import yaml
from dotenv import load_dotenv

API_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_CONFIG = Path("config.yaml")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and rank broad retail seed phrases using OpenAI model knowledge."
    )
    parser.add_argument(
        "seeds",
        nargs="*",
        help="starting seed phrases; defaults to run.seeds in config.yaml",
    )
    parser.add_argument("--count", type=int, default=30, help="number of candidates (default: 30)")
    parser.add_argument("--market", default="United States", help="target geographic market")
    parser.add_argument(
        "--audience",
        default="a broad clothing and apparel retailer serving women, men, and unisex shoppers",
        help="retailer position and audience",
    )
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help="YAML config containing run.seeds (default: config.yaml)")
    return parser.parse_args(argv)


def load_seeds(cli_seeds: list[str], config_path: Path) -> list[str]:
    values = cli_seeds
    if not values:
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except FileNotFoundError as exc:
            raise ValueError(f"no CLI seeds and config file not found: {config_path}") from exc
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError(f"cannot read seed config {config_path}: {exc}") from exc
        values = config.get("run", {}).get("seeds", []) if isinstance(config, dict) else []
        if not isinstance(values, list):
            raise ValueError(f"expected run.seeds to be a list in {config_path}")
        values = [str(value) for value in values]

    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = " ".join(value.strip().split())
        key = clean.casefold()
        if clean and key not in seen:
            seen.add(key)
            unique.append(clean)
    if not unique:
        raise ValueError("no usable seed phrases were provided or found")
    return unique


def response_schema(count: int) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {
                    "type": "object",
                    "properties": {
                        "seed_phrase": {"type": "string"},
                        "category": {"type": "string"},
                        "score": {"type": "integer", "minimum": 0, "maximum": 100},
                        "breadth": {"type": "integer", "minimum": 0, "maximum": 100},
                        "retailer_relevance": {"type": "integer", "minimum": 0, "maximum": 100},
                        "trend_potential": {"type": "integer", "minimum": 0, "maximum": 100},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "reason": {"type": "string"},
                    },
                    "required": [
                        "seed_phrase", "category", "score", "breadth",
                        "retailer_relevance", "trend_potential", "confidence", "reason",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["candidates"],
        "additionalProperties": False,
    }


def build_prompt(seeds: list[str], market: str, audience: str, count: int) -> str:
    return f"""You are selecting broad seed phrases for a keyword-volume expansion run.

Business: {audience}
Market: {market}
Existing seeds: {json.dumps(seeds, ensure_ascii=False)}
Return exactly {count} unique candidate seed phrases.

Use only your learned market knowledge and reasoning. You have no live web, search-volume,
or Google Trends data, so do not claim that you researched or measured current demand.

Candidate rules:
- Treat every existing seed as intentional evidence from the user, not as a suggestion to replace.
- Preserve the meaning and commercially important anchor words of the existing seeds. In
  particular, do not drop modifiers such as "online", "store", "shop", audience, product,
  style, fit, or use-case terms when they carry search intent.
- Generate close, natural seed-phrase expansions around the existing seeds. Rank phrases
  that retain their intent ahead of unrelated coverage ideas.
- Every candidate must be directly traceable to at least one existing seed. Do not introduce
  new departments, audiences, materials, occasions, or merchandising categories merely to
  create variety.
- Original seeds are eligible candidates and should remain highly ranked when useful.
- Avoid near-duplicates, awkward SEO phrases, specific retailer names, trademark-dependent
  phrases, and long-tail queries that are better outputs than seeds.

Scoring:
- score: overall priority for the next keyword research run.
- breadth: 0-100, likely variety of useful expansions without losing original intent.
- retailer_relevance: 0-100, usefulness to this retailer's commercial discovery.
- trend_potential: 0-100, inferred durability or momentum from learned consumer/category patterns;
  this is not a live trend measurement.
- confidence: confidence in the model-inferred ranking.
- reason: at most 12 words, explaining why this seed earns its position.
"""


def extract_output_text(payload: dict[str, Any]) -> str:
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                return content["text"]
    raise ValueError("OpenAI response did not contain output text")


def rank_seeds(api_key: str, model: str, seeds: list[str], market: str,
               audience: str, count: int) -> list[dict[str, Any]]:
    body = {
        "model": model,
        "reasoning": {"effort": "medium"},
        "input": build_prompt(seeds, market, audience, count),
        "text": {
            "verbosity": "low",
            "format": {
                "type": "json_schema",
                "name": "ranked_seed_phrases",
                "strict": True,
                "schema": response_schema(count),
            },
        },
    }
    try:
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=180,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        detail = ""
        if getattr(exc, "response", None) is not None:
            try:
                detail = ": " + exc.response.json().get("error", {}).get("message", "")
            except (ValueError, AttributeError):
                detail = ": " + exc.response.text[:300]
        raise RuntimeError(f"OpenAI request failed{detail or ': ' + str(exc)}") from exc

    try:
        result = json.loads(extract_output_text(response.json()))
        candidates = result["candidates"]
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not parse OpenAI ranking: {exc}") from exc
    return sorted(candidates, key=lambda item: (-item["score"], item["seed_phrase"].casefold()))


def print_table(candidates: list[dict[str, Any]]) -> None:
    headers = ["#", "Seed phrase", "Score", "Breadth", "Retail", "Trend*", "Conf.", "Category", "Why"]
    rows = []
    for index, item in enumerate(candidates, 1):
        rows.append([
            str(index), item["seed_phrase"], str(item["score"]), str(item["breadth"]),
            str(item["retailer_relevance"]), str(item["trend_potential"]),
            item["confidence"], item["category"], item["reason"],
        ])
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]
    print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(value.ljust(widths[i]) for i, value in enumerate(row)))
    print("\n* Trend is model-inferred, not live Google Trends data.")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    if not 5 <= args.count <= 100:
        print("ERROR: --count must be between 5 and 100", file=sys.stderr)
        return 2
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: set OPENAI_API_KEY in .env or the environment", file=sys.stderr)
        return 2
    try:
        seeds = load_seeds(args.seeds, args.config)
        candidates = rank_seeds(
            api_key=api_key,
            model=args.model,
            seeds=seeds,
            market=args.market,
            audience=args.audience,
            count=args.count,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print_table(candidates)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
