"""Normalize raw DataForSEO keyword_overview items into KeywordRecord objects,
and compute per-keyword trend slopes from monthly history."""
from __future__ import annotations

import math
from typing import List, Optional

from .config import Config
from .intent import commercial_intent_score
from .models import KeywordRecord


def _least_squares_slope(values: List[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return num / den


def compute_trend_slope(monthly_history: List, periods: int) -> Optional[float]:
    """Relative linear slope of the last `periods` months of volume.
    Normalised by the mean volume so the value is scale-free (~[-1, 1])."""
    if not monthly_history:
        return None
    # monthly_history: list of {"year","month","search_volume"}
    series = sorted(
        (m.get("year", 0), m.get("month", 0), m.get("search_volume") or 0)
        for m in monthly_history
    )
    volumes = [float(v) for _, _, v in series]
    tail = volumes[-periods:] if len(volumes) >= periods else volumes
    slope = _least_squares_slope(tail)
    mean_vol = (sum(tail) / len(tail)) if tail else 0.0
    if mean_vol <= 0:
        return 0.0
    rel = slope / mean_vol
    # clamp to [-1, 1]
    return max(-1.0, min(1.0, rel))


def normalize_item(item: dict, seed: str, raw_ref: Optional[str],
                   config: Config) -> Optional[KeywordRecord]:
    """Map a raw keyword_overview item to a KeywordRecord. Returns None when
    the item carries no usable keyword_info (treated as a missing-data row)."""
    keyword = item.get("keyword")
    if not keyword:
        return None
    kinfo = item.get("keyword_info") or {}
    props = item.get("keyword_properties") or {}
    sinfo = item.get("search_intent_info") or {}

    monthly = kinfo.get("monthly_searches") or []
    history = [
        (m.get("year"), m.get("month"), m.get("search_volume") or 0)
        for m in monthly
    ]
    main_intent = sinfo.get("main_intent")
    slope = compute_trend_slope(monthly, config.filters.declining_periods)

    rec = KeywordRecord(
        keyword=keyword,
        seed=seed,
        search_volume=kinfo.get("search_volume"),
        cpc=kinfo.get("cpc"),
        competition=kinfo.get("competition"),
        competition_level=kinfo.get("competition_level"),
        keyword_difficulty=props.get("keyword_difficulty"),
        main_intent=main_intent,
        monthly_history=history,
        trend_slope=slope if slope is not None else 0.0,
        commercial_intent=commercial_intent_score(keyword, main_intent, config),
        raw_ref=raw_ref,
    )
    return rec


def has_metrics(rec: KeywordRecord) -> bool:
    """A record counts as usable for scoring when it has at least volume."""
    return rec.search_volume is not None and rec.search_volume > 0


def trend_to_zero_one(slope: Optional[float]) -> float:
    """Map a [-1, 1] trend slope onto [0, 1]."""
    if slope is None:
        return 0.5
    return (slope + 1.0) / 2.0


def normalize_volume(volume: Optional[int], max_volume: float,
                     log_base: float) -> float:
    """Log-scaled volume normalisation to [0, 1]."""
    if not volume or volume <= 0:
        return 0.0
    denom = math.log(max(max_volume, 1.0) + 1.0, log_base)
    if denom <= 0:
        return 0.0
    return max(0.0, min(1.0, math.log(volume + 1.0, log_base) / denom))
