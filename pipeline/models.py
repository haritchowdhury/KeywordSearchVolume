"""Data models for normalized keyword records and clusters."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple


@dataclass
class KeywordRecord:
    keyword: str
    seed: str
    search_volume: Optional[int] = None
    cpc: Optional[float] = None
    competition: Optional[float] = None
    competition_level: Optional[str] = None
    keyword_difficulty: Optional[int] = None
    main_intent: Optional[str] = None
    monthly_history: List[Tuple[int, int, int]] = field(default_factory=list)  # (year, month, vol)
    trend_slope: Optional[float] = None        # relative slope, ~[-1,1]
    commercial_intent: float = 0.0             # 0..1
    cluster_id: Optional[str] = None
    cluster_label: Optional[str] = None
    flags: List[str] = field(default_factory=list)
    opportunity_score: Optional[int] = None
    recommended: bool = False
    raw_ref: Optional[str] = None              # path to verbatim raw API response
    merged_into: Optional[str] = None          # set when deduped into a canonical keyword
    source_seeds: List[str] = field(default_factory=list)
    variant_group_id: Optional[str] = None
    variant_canonical: Optional[str] = None
    lane: str = "category_discovery"
    facets: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_active(self) -> bool:
        """A record that survived dedup (not merged into another)."""
        return self.merged_into is None


@dataclass
class Cluster:
    label: str
    records: List[KeywordRecord] = field(default_factory=list)
    combined_volume: int = 0
    avg_cpc: float = 0.0
    avg_commercial_intent: float = 0.0
    trend_score: float = 0.0
    opportunity_score: int = 0
    recommended: bool = False
    cluster_id: str = ""
    headline_volume: int = 0
    adjusted_cluster_volume: int = 0
    raw_variant_volume: int = 0
    variant_groups: List[dict] = field(default_factory=list)
    source_seeds: List[str] = field(default_factory=list)
    lane_counts: Dict[str, int] = field(default_factory=dict)
    facets: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def keywords(self) -> List[str]:
        return [r.keyword for r in self.records]

    def to_dict(self) -> dict:
        return {
            "cluster": self.label,
            "cluster_id": self.cluster_id,
            "keywords": self.keywords,
            "combined_volume": self.combined_volume,
            "headline_volume": self.headline_volume,
            "adjusted_cluster_volume": self.adjusted_cluster_volume,
            "raw_variant_volume": self.raw_variant_volume,
            "variant_groups": self.variant_groups,
            "source_seeds": self.source_seeds,
            "lane_counts": self.lane_counts,
            "facets": self.facets,
            "avg_cpc": round(self.avg_cpc, 2),
            "commercial_intent": round(self.avg_commercial_intent, 2),
            "trend_score": round(self.trend_score, 2),
            "opportunity_score": self.opportunity_score,
            "recommended_for_store_discovery": self.recommended,
        }
