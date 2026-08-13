"""Tests for token-overlap clustering."""
from __future__ import annotations

from pipeline.cluster import cluster_keywords
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
