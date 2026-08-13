"""Output writers: JSON + CSV, with raw responses kept strictly separate
from normalized data."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import List

from .models import Cluster, KeywordRecord


def write_clusters_json(clusters: List[Cluster], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [c.to_dict() for c in clusters]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def write_clusters_csv(clusters: List[Cluster], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "cluster", "combined_volume", "avg_cpc", "commercial_intent",
        "trend_score", "opportunity_score",
        "recommended_for_store_discovery", "num_keywords", "keywords",
    ]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for c in clusters:
            d = c.to_dict()
            w.writerow([
                d["cluster"], d["combined_volume"], d["avg_cpc"],
                d["commercial_intent"], d["trend_score"], d["opportunity_score"],
                d["recommended_for_store_discovery"], len(c.keywords),
                "|".join(c.keywords),
            ])
    return path


def write_keywords_json(records: List[KeywordRecord], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "keyword": r.keyword,
            "seed": r.seed,
            "search_volume": r.search_volume,
            "cpc": r.cpc,
            "competition": r.competition,
            "competition_level": r.competition_level,
            "keyword_difficulty": r.keyword_difficulty,
            "main_intent": r.main_intent,
            "commercial_intent": round(r.commercial_intent, 2),
            "monthly_history": [
                {"year": year, "month": month, "search_volume": volume}
                for year, month, volume in r.monthly_history
            ],
            "trend_slope": round(r.trend_slope, 3) if r.trend_slope is not None else None,
            "cluster": r.cluster_label,
            "flags": r.flags,
            "opportunity_score": r.opportunity_score,
            "recommended": r.recommended,
            "merged_into": r.merged_into,
            "raw_ref": r.raw_ref,
        }
        for r in records
    ]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def write_keywords_csv(records: List[KeywordRecord], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "keyword", "seed", "search_volume", "cpc", "competition",
        "competition_level", "keyword_difficulty", "main_intent",
        "commercial_intent", "trend_slope", "cluster", "flags",
        "opportunity_score", "recommended", "merged_into", "raw_ref",
        "monthly_history",
    ]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in records:
            w.writerow([
                r.keyword, r.seed, r.search_volume, r.cpc, r.competition,
                r.competition_level, r.keyword_difficulty, r.main_intent,
                round(r.commercial_intent, 2),
                round(r.trend_slope, 3) if r.trend_slope is not None else "",
                r.cluster_label or "",
                ";".join(r.flags),
                r.opportunity_score, r.recommended,
                r.merged_into or "", r.raw_ref or "",
                json.dumps([
                    {"year": year, "month": month, "search_volume": volume}
                    for year, month, volume in r.monthly_history
                ], separators=(",", ":")),
            ])
    return path
