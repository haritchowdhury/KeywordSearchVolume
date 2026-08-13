"""Tests for token-overlap clustering."""
from __future__ import annotations

from pipeline.cluster import attach_variants, cluster_keywords
from pipeline.dedup import dedup_variants
from pipeline.models import KeywordRecord


def _rec(keyword, volume=1000):
    return KeywordRecord(keyword=keyword, seed="s", search_volume=volume)


def test_paddle_variants_cluster_together(cfg):
    records = [
        _rec("pickleball paddles", 201000),
        _rec("carbon fiber pickleball paddle", 18100),
        _rec("professional pickleball paddles", 8100),
        _rec("best pickleball paddle", 90500),
    ]
    clusters = cluster_keywords(records, cfg)
    # all share "pickleball" + "paddle" tokens -> single cluster
    assert len(clusters) == 1
    c = clusters[0]
    assert c.label == "pickleball paddles"  # highest volume
    assert set(c.keywords) == {r.keyword for r in records}


def test_disjoint_topics_split(cfg):
    records = [
        _rec("pickleball paddles", 201000),
        _rec("pickleball paddle grip", 5400),
        _rec("running shoes", 450000),
        _rec("best running shoes", 135000),
        _rec("carbon plate running shoes", 27100),
    ]
    clusters = cluster_keywords(records, cfg)
    labels = {c.label for c in clusters}
    # two clear topic groups
    assert len(clusters) >= 2
    assert "pickleball paddles" in labels
    assert "running shoes" in labels
    shoe_cluster = next(c for c in clusters if c.label == "running shoes")
    assert "best running shoes" in shoe_cluster.keywords


def test_cluster_id_assigned(cfg):
    records = [
        _rec("pickleball paddles", 201000),
        _rec("pickleball paddle bag", 4400),
    ]
    clusters = cluster_keywords(records, cfg)
    assert all(r.cluster_id is not None for c in clusters for r in c.records)
    assert clusters[0].records[0].cluster_label == clusters[0].label


def test_bridge_phrase_does_not_merge_apparel_topics(cfg):
    records = [
        _rec("women's active clothing", 90500),
        _rec("activewear clothing for women", 90500),
        _rec("streetwear clothing for women", 1600),
        _rec("supreme streetwear", 673000),
    ]
    records[-1].main_intent = "navigational"
    clusters = cluster_keywords(records, cfg)
    activewear = next(r for r in records if r.keyword.startswith("activewear"))
    streetwear = next(r for r in records if r.keyword.startswith("streetwear"))
    supreme = next(r for r in records if r.keyword.startswith("supreme"))
    assert activewear.cluster_id != streetwear.cluster_id
    assert supreme.cluster_id != streetwear.cluster_id
    assert supreme.lane == "brand_competitor"


def test_cluster_ids_are_stable(cfg):
    first = cluster_keywords([_rec("running shoes"), _rec("best running shoes")], cfg)
    second = cluster_keywords([_rec("running shoes"), _rec("best running shoes")], cfg)
    assert first[0].cluster_id == second[0].cluster_id


def test_grouped_variants_accumulate_volume_and_report_overlap(cfg):
    records = [
        _rec("women activewear", 90000),
        _rec("women's activewear", 90000),
        _rec("activewear for ladies", 90000),
    ]
    for record in records:
        record.cpc = 1.2
        record.competition = 0.5
        record.keyword_difficulty = 20
        record.monthly_history = [(2026, month, 90000) for month in range(1, 7)]
    deduped = dedup_variants(records, cfg)
    clusters = cluster_keywords([r for r in deduped if r.is_active], cfg)
    attach_variants(clusters, deduped)
    cluster = clusters[0]
    assert cluster.raw_variant_volume == 270000
    assert cluster.combined_volume == 270000
    assert cluster.adjusted_cluster_volume == 90000
