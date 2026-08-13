"""Deduplicate near-variant keywords (e.g. plural/singular, word reorders)
using a normalized token Jaccard similarity against a configurable threshold."""
from __future__ import annotations

import re
import hashlib
from typing import Dict, List, Set

from .config import Config
from .models import KeywordRecord

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# High-value normalisations for retail language. These are deliberately
# conservative: they collapse genuine wording variants without pretending
# that related product categories are identical.
TOKEN_ALIASES = {
    "woman": "women", "womens": "women", "female": "women", "females": "women",
    "lady": "women", "ladies": "women",
    "man": "men", "mens": "men", "male": "men", "males": "men",
    "clothes": "clothing", "apparel": "clothing", "attire": "clothing",
    "shops": "store", "shop": "store", "stores": "store",
    "retailer": "store", "retailers": "store",
    "outfits": "outfit", "hoodies": "hoodie", "shirts": "shirt",
    "jackets": "jacket", "coats": "coat", "dresses": "dress",
    "skirts": "skirt", "pants": "pant", "jeans": "jean",
    "shoes": "shoe", "paddles": "paddle",
}


def tokenize(text: str, strip_tokens: Set[str]) -> List[str]:
    # Remove possessive suffixes before tokenisation so "women's" does not
    # become the two tokens "women" and "s".
    clean = re.sub(r"(?i)([a-z]+)['’]s\b", r"\1", text)
    raw = _TOKEN_RE.findall(clean.lower())
    return [t for t in raw if t not in strip_tokens]


def signature(keyword: str, strip_tokens: Set[str]) -> frozenset:
    """A normalized token signature: lowercase, stop-stripped, singular-collapsed
    (so "paddle"/"paddles" share tokens). Used by both dedup and clustering."""
    toks = tokenize(keyword, strip_tokens)
    norm = set()
    for t in toks:
        aliased = TOKEN_ALIASES.get(t)
        if aliased:
            norm.add(aliased)
        elif t.endswith("s") and len(t) > 4 and not t.endswith(("ss", "us", "is")):
            norm.add(t[:-1])
        else:
            norm.add(t)
    return frozenset(norm)


def compact_signature(keyword: str) -> str:
    """Punctuation-insensitive form for variants such as `s & s` / `ss`."""
    return "".join(_TOKEN_RE.findall(keyword.lower()))


def stable_id(prefix: str, text: str) -> str:
    digest = hashlib.blake2s(text.encode("utf-8"), digest_size=6).hexdigest()
    return f"{prefix}_{digest}"


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
    compact = {id(r): compact_signature(r.keyword) for r in active}

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
            if (jaccard(sigs[id(ri)], sigs[id(rj)]) >= threshold
                    or compact[id(ri)] == compact[id(rj)]):
                union(id(ri), id(rj))

    groups: Dict[int, List[KeywordRecord]] = {}
    for r in active:
        groups.setdefault(find(id(r)), []).append(r)

    result: List[KeywordRecord] = []
    for members in groups.values():
        # canonical = highest volume, then prefer the shortest readable form.
        canonical = max(
            members,
            key=lambda r: (r.search_volume or 0, -len(r.keyword)),
        )
        all_seeds = sorted({s for m in members for s in (m.source_seeds or [m.seed])})
        group_id = stable_id("v", " ".join(sorted(sigs[id(canonical)])))
        canonical.source_seeds = all_seeds
        canonical.variant_group_id = group_id
        canonical.variant_canonical = canonical.keyword
        result.append(canonical)
        for m in members:
            if m is not canonical:
                m.merged_into = canonical.keyword
                m.source_seeds = all_seeds
                m.variant_group_id = group_id
                m.variant_canonical = canonical.keyword
                result.append(m)   # keep for traceability, marked non-active
    return result
