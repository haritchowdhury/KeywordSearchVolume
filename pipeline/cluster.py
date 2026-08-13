"""Topic clustering, retail lanes, facets, and overlap-aware volume totals.

The previous implementation used connected components over pairwise Jaccard
matches. That is single-link clustering: A can pull C into a cluster through B
even when A and C share nothing. This module uses representative + complete
link checks so bridge phrases cannot collapse the whole market into one topic.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Set

from .config import Config
from .dedup import signature, stable_id
from .models import Cluster, KeywordRecord


AUDIENCE = {"women", "men", "kid", "kids", "baby", "unisex", "family"}
CHANNEL = {"online", "store", "boutique", "outlet", "retail", "shopping", "shipping"}
GENERIC = {
    "clothing", "fashion", "wear", "brand", "brands", "best", "cheap", "sale",
    "discount", "deal", "price", "premium", "luxury", "top", "trending", "near",
    "me", "close", "owned", "black", "new", "older", "young",
}
CATEGORY_TERMS = {
    "activewear": {"activewear", "yoga"},
    "streetwear": {"streetwear"},
    "swimwear": {"swimwear", "bathing", "swimsuit"},
    "outerwear": {"jacket", "coat", "outerwear"},
    "tops": {"top", "shirt", "hoodie", "sweatshirt", "sweater", "tee"},
    "bottoms": {"pant", "jean", "trouser", "skirt", "shorts"},
    "dresses": {"dress", "gown"},
    "underwear": {"underwear", "lingerie", "bra", "brief"},
    "sleepwear": {"sleepwear", "pajama", "loungewear"},
    "footwear": {"shoe", "sneaker", "boot", "sandal"},
    "accessories": {"belt", "bag", "hat", "accessory", "jewelry"},
}
FIT_TERMS = {
    "plus size": {"plus", "size"}, "big and tall": {"big", "tall"},
    "petite": {"petite"}, "maternity": {"maternity"}, "oversized": {"oversized"},
}
MODIFIER_TERMS = {
    "affordable": {"cheap", "affordable", "discount", "sale"},
    "luxury": {"luxury", "premium"}, "sustainable": {"sustainable", "ethical"},
    "vintage": {"vintage"}, "consignment": {"consignment"},
}
KNOWN_RETAIL = set().union(AUDIENCE, CHANNEL, GENERIC, *CATEGORY_TERMS.values(),
                           *FIT_TERMS.values(), *MODIFIER_TERMS.values())


def _jac(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _tokens(keyword: str, strip: Set[str]) -> Set[str]:
    return set(signature(keyword, strip))


def _facets(tokens: Set[str], keyword: str) -> Dict[str, List[str]]:
    audience = sorted(tokens & AUDIENCE)
    categories = sorted(name for name, terms in CATEGORY_TERMS.items() if tokens & terms)
    fits = sorted(name for name, terms in FIT_TERMS.items() if terms <= tokens or (len(terms) == 1 and tokens & terms))
    modifiers = sorted(name for name, terms in MODIFIER_TERMS.items() if tokens & terms)
    channels = []
    if "online" in tokens:
        channels.append("online")
    if tokens & (CHANNEL - {"online"}):
        channels.append("store")
    if re.search(r"\b(near me|close to me|closest|nearest)\b", keyword.lower()):
        channels.append("local")
    return {
        "audience": audience,
        "category": categories,
        "channel": sorted(set(channels)),
        "fit": fits,
        "modifier": modifiers,
    }


def _lane(record: KeywordRecord, tokens: Set[str]) -> str:
    low = record.keyword.lower()
    if re.search(r"\b(near me|close to me|closest|nearest|nyc|new york|in [a-z]+)\b", low):
        return "local_discovery"
    if "brand" in tokens or "brands" in tokens:
        return "brand_competitor"
    unknown = tokens - KNOWN_RETAIL
    if (record.main_intent or "").lower() == "navigational" and unknown:
        return "brand_competitor"
    if unknown and tokens & CHANNEL:
        return "brand_competitor"
    if tokens & CHANNEL:
        return "store_discovery"
    return "category_discovery"


def _topic_tokens(record: KeywordRecord, tokens: Set[str]) -> Set[str]:
    """Remove cross-topic facets, retaining a meaningful fallback for broad terms."""
    core = tokens - AUDIENCE - CHANNEL - GENERIC
    if record.lane == "brand_competitor":
        unknown = tokens - KNOWN_RETAIL
        if unknown:
            return unknown | (core & set().union(*CATEGORY_TERMS.values()))
    if core:
        return core
    audience = tokens & AUDIENCE
    if audience:
        return audience | {"clothing"}
    return {"clothing"} if "clothing" in tokens else tokens


def _compatible(a: KeywordRecord, b: KeywordRecord) -> bool:
    # Branded demand is useful but must never name or bridge an unbranded topic.
    return (a.lane == "brand_competitor") == (b.lane == "brand_competitor")


def _representative(members: List[KeywordRecord], topics: Dict[int, Set[str]]) -> KeywordRecord:
    def rank(rec: KeywordRecord):
        sims = [_jac(topics[id(rec)], topics[id(other)]) for other in members]
        centrality = sum(sims) / len(sims)
        non_nav = (rec.main_intent or "").lower() != "navigational"
        return (centrality, non_nav, -len(topics[id(rec)]), rec.search_volume or 0,
                -len(rec.keyword))
    return max(members, key=rank)


def _cluster_label(members: List[KeywordRecord], topics: Dict[int, Set[str]]) -> str:
    representative = _representative(members, topics)
    if len(members) < 4 or all(r.lane == "brand_competitor" for r in members):
        return representative.keyword
    category_counts = Counter(v for r in members for v in r.facets.get("category", []))
    audience_counts = Counter(v for r in members for v in r.facets.get("audience", []))
    fit_counts = Counter(v for r in members for v in r.facets.get("fit", []))
    category = category_counts.most_common(1)[0][0] if category_counts and category_counts.most_common(1)[0][1] >= len(members) * 0.75 else ""
    audience = audience_counts.most_common(1)[0][0] if audience_counts and audience_counts.most_common(1)[0][1] >= len(members) * 0.75 else ""
    fit = fit_counts.most_common(1)[0][0] if fit_counts and fit_counts.most_common(1)[0][1] >= len(members) * 0.75 else ""
    audience_label = {"women": "women's", "men": "men's", "kid": "kids'", "kids": "kids'"}.get(audience, audience)
    if category:
        if category in {"activewear", "streetwear"}:
            return " ".join(x for x in (audience_label, fit, category) if x)
        return representative.keyword
    if fit:
        return " ".join(x for x in (audience_label, fit, "clothing") if x)
    if audience:
        store_share = sum(r.lane in {"store_discovery", "local_discovery"} for r in members) / len(members)
        if store_share >= 0.6:
            return f"{audience_label} clothing stores"
        return f"{audience_label} clothing"
    return representative.keyword


def cluster_keywords(records: List[KeywordRecord], config: Config) -> List[Cluster]:
    """Build non-transitive topic clusters from active keyword records."""
    threshold = config.clustering.similarity_threshold
    strip = set(config.dedup.strip_tokens or [])
    active = [r for r in records if r.is_active]
    topics: Dict[int, Set[str]] = {}
    for record in active:
        toks = _tokens(record.keyword, strip)
        record.facets = _facets(toks, record.keyword)
        record.lane = _lane(record, toks)
        topics[id(record)] = _topic_tokens(record, toks)

    # High-volume representatives establish clusters first. A candidate must
    # match both the representative and every member, preventing bridge chains.
    groups: List[List[KeywordRecord]] = []
    for record in sorted(active, key=lambda r: (r.search_volume or 0), reverse=True):
        best_group = None
        best_score = -1.0
        for members in groups:
            rep = _representative(members, topics)
            if not _compatible(record, rep):
                continue
            rep_score = _jac(topics[id(record)], topics[id(rep)])
            minimum = min(_jac(topics[id(record)], topics[id(m)]) for m in members)
            if rep_score >= threshold and minimum > 0 and rep_score > best_score:
                best_group, best_score = members, rep_score
        if best_group is None:
            groups.append([record])
        else:
            best_group.append(record)

    clusters: List[Cluster] = []
    for members in groups:
        label_rec = _representative(members, topics)
        label = _cluster_label(members, topics)
        cid = stable_id("c", label.lower() + "|" + label_rec.keyword.lower() + "|" + label_rec.lane)
        for member in members:
            member.cluster_id = cid
            member.cluster_label = label
        cluster = Cluster(label=label, records=members, cluster_id=cid)
        _aggregate_metadata(cluster, members)
        clusters.append(cluster)
    clusters.sort(key=lambda c: (-c.adjusted_cluster_volume, c.label.lower()))
    return clusters


def _metric_fingerprint(record: KeywordRecord) -> tuple:
    history = tuple(v for _, _, v in record.monthly_history)
    # Matching history plus matching overview metrics is much stronger evidence
    # of a shared Google close-variant bucket than equal volume alone.
    return (record.search_volume or 0, history, record.cpc, record.competition,
            record.keyword_difficulty)


def _aggregate_metadata(cluster: Cluster, records: Iterable[KeywordRecord]) -> None:
    rows = list(records)
    unique_variants: Dict[str, int] = {}
    for row in rows:
        key = row.keyword.strip().lower()
        unique_variants[key] = max(unique_variants.get(key, 0), row.search_volume or 0)
    cluster.raw_variant_volume = sum(unique_variants.values())
    # `combined_volume` remains the compatibility field, but now follows the
    # intuitive business meaning: cumulative traffic across distinct phrases.
    cluster.combined_volume = cluster.raw_variant_volume
    cluster.headline_volume = max((r.search_volume or 0 for r in rows), default=0)
    distinct_rows: Dict[str, KeywordRecord] = {}
    for row in rows:
        key = row.keyword.strip().lower()
        current = distinct_rows.get(key)
        if current is None or (row.search_volume or 0) > (current.search_volume or 0):
            distinct_rows[key] = row
    buckets: Dict[tuple, int] = {}
    for row in distinct_rows.values():
        fp = _metric_fingerprint(row)
        buckets[fp] = max(buckets.get(fp, 0), row.search_volume or 0)
    cluster.adjusted_cluster_volume = sum(buckets.values())
    cluster.source_seeds = sorted({s for r in rows for s in (r.source_seeds or [r.seed])})
    cluster.lane_counts = dict(sorted(Counter(r.lane for r in rows).items()))
    facet_values: Dict[str, Set[str]] = defaultdict(set)
    for row in rows:
        for name, values in row.facets.items():
            facet_values[name].update(values)
    cluster.facets = {name: sorted(values) for name, values in facet_values.items()}


def attach_variants(clusters: List[Cluster], all_records: List[KeywordRecord]) -> None:
    """Attach merged variants to their canonical cluster and finalise totals."""
    canonical_by_name = {r.keyword: r for c in clusters for r in c.records}
    cluster_by_id = {c.cluster_id: c for c in clusters}
    rows_by_cluster: Dict[str, List[KeywordRecord]] = defaultdict(list)
    for record in all_records:
        canonical = canonical_by_name.get(record.merged_into or record.keyword)
        if canonical is None:
            continue
        record.cluster_id = canonical.cluster_id
        record.cluster_label = canonical.cluster_label
        record.lane = canonical.lane
        record.facets = canonical.facets
        rows_by_cluster[canonical.cluster_id].append(record)

    for cid, rows in rows_by_cluster.items():
        cluster = cluster_by_id[cid]
        groups: Dict[str, List[KeywordRecord]] = defaultdict(list)
        for row in rows:
            groups[row.variant_group_id or stable_id("v", row.keyword)].append(row)
        payload = []
        for group_id, variants in groups.items():
            canonical = next((r for r in variants if r.is_active), variants[0])
            payload.append({
                "variant_group_id": group_id,
                "canonical": canonical.keyword,
                "variants": sorted({r.keyword for r in variants}),
                "volume": canonical.search_volume or 0,
                "source_seeds": sorted({s for r in variants for s in (r.source_seeds or [r.seed])}),
            })
        cluster.variant_groups = sorted(payload, key=lambda g: (-g["volume"], g["canonical"]))
        _aggregate_metadata(cluster, rows)
