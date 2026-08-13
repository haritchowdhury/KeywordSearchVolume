"""Deduplicate near-variant keywords (e.g. plural/singular, word reorders)
using a normalized token Jaccard similarity against a configurable threshold."""
from __future__ import annotations

import re
import string
from typing import Dict, List, Set

from .config import Config
from .models import KeywordRecord

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str, strip_tokens: Set[str]) -> List[str]:
    raw = _TOKEN_RE.findall(text.lower())
    return [t for t in raw if t not in strip_tokens]


def signature(keyword: str, strip_tokens: Set[str]) -> frozenset:
    """A normalized token signature: lowercase, stop-stripped, singular-collapsed
    (so "paddle"/"paddles" share tokens). Used by both dedup and clustering."""
    toks = tokenize(keyword, strip_tokens)
    norm = set()
    for t in toks:
        # crude singular collapse: drop a trailing 's' on longer tokens
        if t.endswith("s") and len(t) > 3:
            norm.add(t[:-1])
        else:
            norm.add(t)
    return frozenset(norm)


# Backwards-compatible alias.
_signature = signature


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def dedup_variants(records: List[KeywordRecord],
                   config: Config) -> List[KeywordRecord]:
    """Merge close-variant records into a single canonical record (the one with
    the highest search volume). Non-canonical records are marked with
    `merged_into` and excluded from downstream processing via `is_active`."""
    threshold = config.dedup.similarity_threshold
    strip = set(config.dedup.strip_tokens or [])

    active = [r for r in records if r.is_active]
    sigs = {id(r): signature(r.keyword, strip) for r in active}

    # Union-find over near-variant groups.
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

    n = len(active)
    for i in range(n):
        ri = active[i]
        if not sigs[id(ri)]:
            continue
        for j in range(i + 1, n):
            rj = active[j]
            if not sigs[id(rj)]:
                continue
            if jaccard(sigs[id(ri)], sigs[id(rj)]) >= threshold:
                union(id(ri), id(rj))

    groups: Dict[int, List[KeywordRecord]] = {}
    for r in active:
        groups.setdefault(find(id(r)), []).append(r)

    result: List[KeywordRecord] = []
    for members in groups.values():
        if len(members) == 1:
            result.append(members[0])
            continue
        # canonical = highest volume, tiebreak keyword length desc
        canonical = max(
            members,
            key=lambda r: (r.search_volume or 0, len(r.keyword)),
        )
        result.append(canonical)
        for m in members:
            if m is not canonical:
                m.merged_into = canonical.keyword
                result.append(m)   # keep for traceability, marked non-active
    return result
