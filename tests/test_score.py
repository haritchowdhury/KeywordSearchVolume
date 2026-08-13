"""Tests for opportunity scoring + flagging + recommendation logic."""
from __future__ import annotations

from pipeline.models import KeywordRecord
from pipeline.score import (BLOCKING_FLAGS, flag_record, score_and_flag_all,
                            score_cluster)
from pipeline.cluster import Cluster


def _rec(keyword, volume, cpc, comp, diff, intent, ci, slope=0.0):
    return KeywordRecord(
        keyword=keyword, seed="s", search_volume=volume, cpc=cpc,
        competition=comp, keyword_difficulty=diff, main_intent=intent,
        commercial_intent=ci, trend_slope=slope,
    )


def test_high_intent_low_difficulty_outscores_broad_info(tmp_cfg):
    a = _rec("carbon fiber pickleball paddle", 18100, 1.82, 0.8, 22,
             "commercial", 0.9, slope=0.3)
    b = _rec("pickleball rules wiki", 90500, 0.05, 0.1, 6,
             "informational", 0.05, slope=-0.1)
    score_and_flag_all([a, b], tmp_cfg)
    assert a.opportunity_score > b.opportunity_score
    assert a.recommended is True
    assert b.recommended is False


def test_recommendation_respects_threshold(tmp_cfg):
    # Very weak record: low volume, informational, high difficulty.
    r = _rec("obscure term", 50, 0.01, 1.0, 95, "informational", 0.05, slope=-0.2)
    score_and_flag_all([r], tmp_cfg)
    assert r.opportunity_score < tmp_cfg.scoring.recommend_threshold
    assert r.recommended is False


def test_flag_too_little_traffic(tmp_cfg):
    r = _rec("micro volume kw", 10, 0.5, 0.3, 20, "commercial", 0.7)
    flag_record(r, tmp_cfg)
    assert "too_little_traffic" in r.flags


def test_flag_declining_traffic(tmp_cfg):
    r = _rec("dying fad widget", 5000, 0.8, 0.4, 25, "commercial", 0.7,
             slope=tmp_cfg.filters.declining_slope_threshold - 0.2)
    flag_record(r, tmp_cfg)
    assert "declining_traffic" in r.flags


def test_flag_too_broad(tmp_cfg):
    # single-word + very high volume -> too_broad
    r = _rec("shoes", 600000, 0.9, 1.0, 80, "commercial", 0.6)
    flag_record(r, tmp_cfg)
    assert "too_broad" in r.flags
    # multi-word high volume should NOT be flagged too_broad
    r2 = _rec("red running shoes", 600000, 0.9, 1.0, 80, "commercial", 0.6)
    flag_record(r2, tmp_cfg)
    assert "too_broad" not in r2.flags


def test_blocking_flags_prevent_recommendation(tmp_cfg):
    r = _rec("declining product", 5000, 1.0, 0.4, 10, "transactional", 0.95,
             slope=tmp_cfg.filters.declining_slope_threshold - 0.2)
    score_and_flag_all([r], tmp_cfg)
    assert set(r.flags) & BLOCKING_FLAGS
    assert r.recommended is False


def test_brand_competitor_stays_visible_but_is_not_recommended(tmp_cfg):
    r = _rec("example brand clothing", 50000, 2.0, 0.7, 10,
             "commercial", 0.95, slope=0.2)
    r.lane = "brand_competitor"
    score_and_flag_all([r], tmp_cfg)
    assert "brand_competitor" in r.flags
    assert r.recommended is False


def test_cluster_scoring_aggregates_members(tmp_cfg):
    members = [
        _rec("pickleball paddles", 201000, 1.34, 1.0, 14, "transactional", 0.95, slope=0.2),
        _rec("best pickleball paddle", 90500, 1.50, 0.9, 18, "commercial", 0.9, slope=0.1),
    ]
    c = Cluster(label="pickleball paddles", records=members)
    score_cluster(c, tmp_cfg)
    assert c.combined_volume == 291500
    assert 0 <= c.opportunity_score <= 100
    assert 0.0 <= c.trend_score <= 1.0
