"""Offline fixtures + a fixture-backed client so the pipeline runs end-to-end
without network access or API credits. Used by `run.py --offline` and by
integration-style tests."""
from __future__ import annotations

from typing import Dict, List

from pipeline.cache import ResponseCache
from pipeline.config import Config


def make_item(keyword: str, volume: int, cpc: float, competition: float,
              difficulty: int, intent: str, trend: int = 0) -> dict:
    """Build a realistic keyword_overview item dict. `trend` controls the
    monthly history slope: positive => rising, negative => declining."""
    months = 8
    base = max(volume, 10)
    monthly = []
    for i in range(months):
        step = (i - months / 2) * (trend / 100.0)
        vol = max(1, int(base * (1.0 + step)))
        monthly.append({"year": 2026, "month": months - i, "search_volume": vol})
    return {
        "se_type": "google",
        "keyword": keyword,
        "location_code": 2840,
        "language_code": "en",
        "keyword_info": {
            "se_type": "google",
            "competition": competition,
            "competition_level": "HIGH" if competition > 0.66 else (
                "MEDIUM" if competition > 0.33 else "LOW"),
            "cpc": cpc,
            "search_volume": volume,
            "monthly_searches": monthly,
        },
        "keyword_properties": {
            "se_type": "google",
            "keyword_difficulty": difficulty,
        },
        "search_intent_info": {
            "se_type": "google",
            "main_intent": intent,
        },
    }


# Seed -> list of keyword items used by the offline client.
_FIXTURES: Dict[str, List[dict]] = {
    "pickleball": [
        make_item("pickleball paddles", 201000, 1.34, 1.0, 14, "transactional", trend=5),
        make_item("carbon fiber pickleball paddle", 18100, 1.82, 0.8, 22, "commercial", trend=12),
        make_item("professional pickleball paddles", 8100, 2.10, 0.7, 30, "commercial", trend=8),
        make_item("best pickleball paddle", 90500, 1.50, 0.9, 18, "commercial", trend=3),
        make_item("pickleball paddle reviews", 12100, 1.10, 0.5, 12, "commercial", trend=-2),
        make_item("what is pickleball", 246000, 0.05, 0.1, 6, "informational", trend=1),
    ],
    "golf accessories": [
        make_item("golf accessories", 33100, 0.74, 0.9, 35, "commercial", trend=-8),
        make_item("best golf accessories", 5400, 1.20, 0.7, 28, "commercial", trend=4),
        make_item("golf accessories gifts", 2900, 0.95, 0.6, 20, "transactional", trend=9),
        make_item("golf tees bulk", 8100, 0.45, 0.8, 16, "transactional", trend=2),
        make_item("golf swing trainer", 9900, 1.65, 0.85, 33, "commercial", trend=6),
    ],
    "running shoes": [
        make_item("running shoes", 450000, 0.88, 1.0, 78, "commercial", trend=-4),
        make_item("best running shoes", 135000, 1.40, 0.95, 70, "commercial", trend=2),
        make_item("carbon plate running shoes", 27100, 1.95, 0.8, 55, "transactional", trend=18),
        make_item("cheap running shoes", 18100, 0.60, 0.9, 48, "transactional", trend=-10),
        make_item("how to tie running shoes", 4400, 0.02, 0.1, 8, "informational", trend=0),
    ],
    "pet supplements": [
        make_item("pet supplements", 27100, 1.10, 0.85, 40, "commercial", trend=14),
        make_item("best pet supplements", 6600, 1.70, 0.7, 32, "commercial", trend=10),
        make_item("dog joint supplements", 22200, 1.45, 0.8, 38, "transactional", trend=11),
        make_item("cat supplements", 8100, 1.05, 0.6, 26, "commercial", trend=7),
        make_item("are pet supplements safe", 2500, 0.10, 0.1, 10, "informational", trend=-1),
    ],
    "home gym equipment": [
        make_item("home gym equipment", 135000, 1.00, 0.95, 65, "commercial", trend=3),
        make_item("best home gym equipment", 8100, 1.55, 0.8, 50, "commercial", trend=5),
        make_item("adjustable dumbbells", 110000, 1.20, 0.9, 60, "transactional", trend=8),
        make_item("power rack for home gym", 9900, 1.35, 0.75, 42, "transactional", trend=9),
        make_item("resistance bands set", 60500, 0.70, 0.85, 36, "transactional", trend=6),
    ],
}


class OfflineClient:
    """Duck-typed client mirroring the methods the pipeline uses:
    `expand(seed)` and `keyword_overview(keywords)`."""

    def __init__(self, config: Config, cache: ResponseCache) -> None:
        self.config = config
        self.cache = cache

    def expand(self, seed: str, market: dict | None = None) -> List[str]:
        items = _FIXTURES.get(seed, [])
        keywords = [it["keyword"] for it in items]
        return keywords or [seed]

    def keyword_overview(self, keywords: List[str], market: dict | None = None) -> List[dict]:
        wanted = set(keywords)
        out: List[dict] = []
        for items in _FIXTURES.values():
            for it in items:
                if it["keyword"] in wanted:
                    out.append(it)
        return out


def build_offline_client(config: Config, cache: ResponseCache) -> OfflineClient:
    return OfflineClient(config, cache)
