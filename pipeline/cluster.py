"""Cluster keywords by topic using token-overlap (Jaccard) union-find."""
from __future__ import annotations

from typing import Dict, List, Set

from .config import Config
from .dedup import signature, tokenize
from .models import Cluster, KeywordRecord


def _token_sets(records: List[KeywordRecord], strip: Set[str]) -> Dict[int, set]:
    # Use the same singular-collapsing signature as dedup so plurals
    # ("paddle"/"paddles") don't artificially split clusters.
    return {id(r): set(signature(r.keyword, strip)) for r in records}


def cluster_keywords(records: List[KeywordRecord],
                     config: Config) -> List[Cluster]:
    """Group active records into topic clusters by Jaccard token overlap."""
    threshold = config.clustering.similarity_threshold
    strip = set(config.dedup.strip_tokens or [])
    active = [r for r in records if r.is_active]
    tokens = _token_sets(active, strip)

    parent = {id(r): id(r) for r in active}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    def jac(a, b):
        if not a or not b:
            return 0.0
        inter = len(a & b)
        union_len = len(a | b)
        return inter / union_len if union_len else 0.0

    n = len(active)
    for i in range(n):
        ti = tokens[id(active[i])]
        for j in range(i + 1, n):
            if jac(ti, tokens[id(active[j])]) >= threshold:
                union(id(active[i]), id(active[j]))

    groups: Dict[int, List[KeywordRecord]] = {}
    for r in active:
        groups.setdefault(find(id(r)), []).append(r)

    strategy = config.clustering.cluster_label_strategy
    clusters: List[Cluster] = []
    for members in groups.values():
        if strategy == "longest":
            label_rec = max(members, key=lambda r: len(r.keyword))
        else:  # highest_volume (default)
            label_rec = max(
                members,
                key=lambda r: (r.search_volume or 0, len(r.keyword)),
            )
        cid = f"c_{abs(hash(label_rec.keyword)) % 10_000_000}"
        for m in members:
            m.cluster_id = cid
            m.cluster_label = label_rec.keyword
        clusters.append(Cluster(label=label_rec.keyword, records=members))
    clusters.sort(key=lambda c: c.label.lower())
    return clusters
