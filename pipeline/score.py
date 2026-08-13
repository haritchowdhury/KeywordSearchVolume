"""Opportunity scoring + flagging. All weights/thresholds come from config."""
from __future__ import annotations

from typing import List, Optional

from .config import Config
from .models import Cluster, KeywordRecord
from .normalize import normalize_volume, trend_to_zero_one

# Flags that disqualify a keyword from store-discovery recommendation.
BLOCKING_FLAGS = {"too_little_traffic", "too_broad", "declining_traffic"}


def flag_record(rec: KeywordRecord, config: Config) -> None:
    rec.flags = []
    filters = config.filters

    volume = rec.search_volume or 0
    if volume < filters.min_volume_keep:
        rec.flags.append("too_little_traffic")

    word_count = len(rec.keyword.split())
    if (word_count <= filters.too_broad_max_words
            and volume >= filters.too_broad_min_volume):
        rec.flags.append("too_broad")

    if rec.trend_slope is not None and rec.trend_slope < filters.declining_slope_threshold:
        rec.flags.append("declining_traffic")


def _population_stats(records: List[KeywordRecord]) -> dict:
    volumes = [r.search_volume or 0 for r in records]
    cpcs = [r.cpc for r in records if r.cpc is not None]
    return {
        "max_volume": float(max(volumes)) if volumes else 1.0,
        "max_cpc": float(max(cpcs)) if cpcs else 1.0,
    }


def score_record(rec: KeywordRecord, stats: dict, config: Config) -> None:
    weights = config.scoring.weights
    scfg = config.scoring

    vol_norm = normalize_volume(
        rec.search_volume, stats["max_volume"], scfg.volume_log_base
    )
    max_cpc = max(stats["max_cpc"], 0.01)
    cpc_norm = max(0.0, min(1.0, (rec.cpc or 0.0) / max_cpc))
    inv_diff = 1.0 - ((rec.keyword_difficulty or 0) / scfg.difficulty_max)
    inv_diff = max(0.0, min(1.0, inv_diff))
    inv_comp = 1.0 - ((rec.competition or 0.0) / scfg.competition_max)
    inv_comp = max(0.0, min(1.0, inv_comp))
    trend_norm = trend_to_zero_one(rec.trend_slope)
    ci = rec.commercial_intent

    raw = (
        weights.volume * vol_norm
        + weights.commercial_intent * ci
        + weights.trend * trend_norm
        + weights.inverse_difficulty * inv_diff
        + weights.inverse_competition * inv_comp
        + weights.cpc * cpc_norm
    )
    # normalise by sum of weights so output is on a stable 0..100 scale
    total_w = sum(weights.values()) or 1.0
    rec.opportunity_score = round(max(0.0, min(1.0, raw / total_w)) * 100)

    blocking = set(rec.flags) & BLOCKING_FLAGS
    rec.recommended = (
        rec.opportunity_score >= config.scoring.recommend_threshold
        and not blocking
    )


def score_and_flag_all(records: List[KeywordRecord], config: Config) -> dict:
    stats = _population_stats(records)
    for rec in records:
        if not rec.is_active:
            continue
        flag_record(rec, config)
        score_record(rec, stats, config)
    return stats


def score_cluster(cluster: Cluster, config: Config) -> None:
    members = cluster.records
    if not members:
        return
    volumes = [m.search_volume or 0 for m in members]
    cpcs = [m.cpc for m in members if m.cpc is not None]
    cis = [m.commercial_intent for m in members]
    trends = [trend_to_zero_one(m.trend_slope) for m in members]

    cluster.combined_volume = int(sum(volumes))
    cluster.avg_cpc = (sum(cpcs) / len(cpcs)) if cpcs else 0.0
    cluster.avg_commercial_intent = (sum(cis) / len(cis)) if cis else 0.0
    cluster.trend_score = (sum(trends) / len(trends)) if trends else 0.0

    blocking_share = sum(
        1 for m in members if set(m.flags) & BLOCKING_FLAGS
    ) / len(members)

    # Score the cluster as a virtual record using its aggregates.
    weights = config.scoring.weights
    scfg = config.scoring
    stats = _population_stats(members)
    vol_norm = normalize_volume(
        cluster.combined_volume, max(stats["max_volume"], 1.0),
        scfg.volume_log_base,
    )
    max_cpc = max(stats["max_cpc"], 0.01)
    cpc_norm = max(0.0, min(1.0, (cluster.avg_cpc or 0.0) / max_cpc))
    inv_diff = 1.0 - (
        (sum(m.keyword_difficulty or 0 for m in members) / len(members))
        / scfg.difficulty_max
    )
    inv_diff = max(0.0, min(1.0, inv_diff))
    inv_comp = 1.0 - (
        sum(m.competition or 0.0 for m in members) / len(members)
    ) / scfg.competition_max
    inv_comp = max(0.0, min(1.0, inv_comp))

    raw = (
        weights.volume * vol_norm
        + weights.commercial_intent * cluster.avg_commercial_intent
        + weights.trend * cluster.trend_score
        + weights.inverse_difficulty * inv_diff
        + weights.inverse_competition * inv_comp
        + weights.cpc * cpc_norm
    )
    total_w = sum(weights.values()) or 1.0
    cluster.opportunity_score = round(
        max(0.0, min(1.0, raw / total_w)) * 100
    )
    cluster.recommended = (
        cluster.opportunity_score >= config.scoring.cluster_recommend_threshold
        and blocking_share < 0.5
    )


def score_all_clusters(clusters: List[Cluster], config: Config) -> None:
    for cluster in clusters:
        score_cluster(cluster, config)
