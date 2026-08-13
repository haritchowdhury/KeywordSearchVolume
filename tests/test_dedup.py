"""Tests for close-variant deduplication."""
from __future__ import annotations

from pipeline.dedup import dedup_variants, jaccard, _signature  # noqa: F401
from pipeline.models import KeywordRecord


def _rec(keyword, volume=1000):
    return KeywordRecord(keyword=keyword, seed="s", search_volume=volume)


def test_plural_singular_merged(cfg):
    records = [
        _rec("pickleball paddle", 5000),
        _rec("pickleball paddles", 8100),   # canonical (higher volume)
    ]
    out = dedup_variants(records, cfg)
    active = [r for r in out if r.is_active]
    assert len(active) == 1
    assert active[0].keyword == "pickleball paddles"
    merged = [r for r in out if not r.is_active]
    assert merged and merged[0].merged_into == "pickleball paddles"


def test_distinct_keywords_kept(cfg):
    records = [
        _rec("pickleball paddle", 5000),
        _rec("carbon fiber pickleball paddle", 8100),
        _rec("pickleball court shoes", 2200),
    ]
    out = dedup_variants(records, cfg)
    active = [r for r in out if r.is_active]
    assert len(active) == 3


def test_word_reorder_near_variant(cfg):
    # high overlap via shared tokens -> merged
    records = [
        _rec("best pickleball paddles", 9000),
        _rec("pickleball paddles best", 8000),
    ]
    out = dedup_variants(records, cfg)
    active = [r for r in out if r.is_active]
    assert len(active) == 1
    assert active[0].keyword == "best pickleball paddles"


def test_jaccard_units():
    from pipeline.dedup import _signature
    strip = {"the", "a", "an"}
    sig_a = _signature("the best paddle", strip)
    sig_b = _signature("best paddles", strip)
    assert jaccard(sig_a, sig_b) > 0.5
    assert jaccard(_signature("shoes", strip), _signature("paddle", strip)) == 0.0


def test_retail_synonyms_are_variants_without_damaging_s_words(cfg):
    records = [
        _rec("women activewear", 9000),
        _rec("women's activewear", 8000),
        _rec("business dress", 7000),
        _rec("business dresses", 6000),
    ]
    out = dedup_variants(records, cfg)
    active = [r.keyword for r in out if r.is_active]
    assert len(active) == 2
    assert "women activewear" in active
    assert "business dress" in active
