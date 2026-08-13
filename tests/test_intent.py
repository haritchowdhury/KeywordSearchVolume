"""Tests for intent scoring and informational filtering."""
from __future__ import annotations

from pipeline.intent import commercial_intent_score, is_informational


def test_transactional_beats_informational(cfg):
    assert commercial_intent_score("buy pickleball paddle", "transactional", cfg) > \
           commercial_intent_score("what is pickleball", "informational", cfg)


def test_commercial_modifier_boosts(cfg):
    base = commercial_intent_score("pickleball paddle", "commercial", cfg)
    boosted = commercial_intent_score("best pickleball paddle", "commercial", cfg)
    assert boosted >= base


def test_informational_modifier_lowers(cfg):
    low = commercial_intent_score("what is pickleball", "commercial", cfg)
    assert low < 0.5


def test_is_informational_by_label(cfg):
    assert is_informational("pickleball rules", "informational", cfg) is True
    assert is_informational("pickleball paddles", "transactional", cfg) is False


def test_is_informational_by_modifier(cfg):
    assert is_informational("how to play pickleball", "commercial", cfg) is True
    assert is_informational("pickleball paddle buy", "transactional", cfg) is False


def test_score_bounded(cfg):
    for kw, intent in [("buy now", "transactional"),
                       ("meaning of dream", "informational"),
                       ("acme brand", "navigational")]:
        sc = commercial_intent_score(kw, intent, cfg)
        assert 0.0 <= sc <= 1.0
