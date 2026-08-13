"""Tests for seasonality-aware trend momentum."""
from pipeline.normalize import compute_trend_slope


def _history(year, values):
    return [
        {"year": year, "month": month, "search_volume": volume}
        for month, volume in enumerate(values, 1)
    ]


def test_same_season_is_not_mistaken_for_structural_decline():
    seasonal = [600, 500, 400, 300, 200, 100]
    history = _history(2025, seasonal) + _history(2026, seasonal)
    momentum = compute_trend_slope(history, 6)
    assert momentum is not None
    assert momentum > -0.05


def test_year_over_year_growth_is_positive():
    history = _history(2025, [100] * 6) + _history(2026, [125] * 6)
    assert compute_trend_slope(history, 6) > 0.15
