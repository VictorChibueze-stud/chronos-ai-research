"""Tests for CHoCH zone computation."""
from dataclasses import dataclass
from typing import Optional

import pytest

from src.core.choch_zone import (
    annotate_legs_with_choch_zones,
    compute_choch_proximity,
    compute_choch_zone,
    get_active_choch_zone,
)


@dataclass
class MockCandle:
    close: float


def _make_leg(
    type: str,
    start_price: float,
    end_price: Optional[float],
    start_index: int,
    end_index: Optional[int],
    confirmed: bool,
) -> dict:
    return {
        "type": type,
        "start_price": start_price,
        "end_price": end_price,
        "start_index": start_index,
        "end_index": end_index,
        "confirmed": confirmed,
        "slope": None,
    }


def _make_zone(lower: float, upper: float) -> dict:
    """Build a minimal CHoCH zone dict for proximity tests."""
    return {
        "lower_boundary": lower,
        "upper_boundary": upper,
        "zone_midpoint": (lower + upper) / 2,
        "zone_width_pct": round((upper - lower) / lower * 100, 2) if lower != 0 else 0.0,
        "trend_direction": "down",
        "source_impulse_start_index": 10,
        "source_impulse_end_index": 15,
        "prior_impulse_end_index": 5,
    }


# ---------------------------------------------------------------------------
# compute_choch_zone
# ---------------------------------------------------------------------------


def test_zone_requires_two_confirmed_impulses():
    legs = [_make_leg("impulse", 100, 80, 0, 5, True)]
    result = compute_choch_zone(legs, "down")
    assert result is None


def test_zone_boundaries_downtrend():
    # Prior impulse: 100 → 80.  Most recent impulse starts at 90 (broke below 80).
    # lower = min(90, 80) = 80, upper = max(90, 80) = 90
    legs = [
        _make_leg("impulse", 100, 80, 0, 5, True),
        _make_leg("impulse", 90, 70, 10, 15, True),
    ]
    result = compute_choch_zone(legs, "down")
    assert result is not None
    assert result["lower_boundary"] == 80.0
    assert result["upper_boundary"] == 90.0


def test_zone_boundaries_uptrend():
    # Prior impulse: 80 → 100.  Most recent impulse starts at 90 (broke above 100).
    # lower = min(90, 100) = 90, upper = max(90, 100) = 100
    legs = [
        _make_leg("impulse", 80, 100, 0, 5, True),
        _make_leg("impulse", 90, 110, 10, 15, True),
    ]
    result = compute_choch_zone(legs, "up")
    assert result is not None
    assert result["lower_boundary"] == 90.0
    assert result["upper_boundary"] == 100.0


def test_zone_width_pct_computed():
    # Downtrend zone: lower=80, upper=90 → (90-80)/80*100 = 12.5
    legs = [
        _make_leg("impulse", 100, 80, 0, 5, True),
        _make_leg("impulse", 90, 70, 10, 15, True),
    ]
    result = compute_choch_zone(legs, "down")
    expected = round((90 - 80) / 80 * 100, 2)
    assert result is not None
    assert result["zone_width_pct"] == expected


# ---------------------------------------------------------------------------
# compute_choch_proximity
# ---------------------------------------------------------------------------


def test_proximity_below_zone():
    zone = _make_zone(80.0, 90.0)
    result = compute_choch_proximity(zone, 75.0)
    assert result["price_below_zone"] is True
    assert result["price_in_zone"] is False
    assert result["price_above_zone"] is False
    assert result["proximity_pct"] < 0


def test_proximity_in_zone():
    zone = _make_zone(80.0, 90.0)
    result = compute_choch_proximity(zone, 85.0)
    assert result["price_in_zone"] is True
    assert result["price_below_zone"] is False
    assert result["price_above_zone"] is False
    assert result["proximity_pct"] == 50.0


def test_proximity_above_zone():
    zone = _make_zone(80.0, 90.0)
    result = compute_choch_proximity(zone, 95.0)
    assert result["price_above_zone"] is True
    assert result["price_in_zone"] is False
    assert result["price_below_zone"] is False
    assert result["proximity_pct"] > 100


def test_proximity_at_exact_lower_boundary():
    zone = _make_zone(80.0, 90.0)
    result = compute_choch_proximity(zone, 80.0)
    assert result["proximity_pct"] == 0.0
    assert result["price_in_zone"] is True
    assert result["price_below_zone"] is False
    assert result["price_above_zone"] is False


def test_proximity_at_exact_upper_boundary():
    zone = _make_zone(80.0, 90.0)
    result = compute_choch_proximity(zone, 90.0)
    assert result["proximity_pct"] == 100.0
    assert result["price_in_zone"] is True
    assert result["price_below_zone"] is False
    assert result["price_above_zone"] is False


# ---------------------------------------------------------------------------
# annotate_legs_with_choch_zones
# ---------------------------------------------------------------------------


def test_annotate_legs_first_impulse_gets_none():
    legs = [_make_leg("impulse", 100, 80, 0, 5, True)]
    annotate_legs_with_choch_zones(legs, "down")
    assert legs[0]["choch_zone"] is None


def test_annotate_legs_second_impulse_gets_zone():
    legs = [
        _make_leg("impulse", 100, 80, 0, 5, True),
        _make_leg("impulse", 90, 70, 10, 15, True),
    ]
    annotate_legs_with_choch_zones(legs, "down")
    assert legs[0]["choch_zone"] is None
    assert legs[1]["choch_zone"] is not None
    assert legs[1]["choch_zone"]["lower_boundary"] == 80.0
    assert legs[1]["choch_zone"]["upper_boundary"] == 90.0


def test_annotate_legs_retracement_gets_none():
    legs = [_make_leg("retracement", 80, 90, 5, 10, True)]
    annotate_legs_with_choch_zones(legs, "down")
    assert legs[0]["choch_zone"] is None


def test_annotate_legs_unconfirmed_gets_none():
    legs = [_make_leg("impulse", 100, 80, 0, 5, False)]
    annotate_legs_with_choch_zones(legs, "down")
    assert legs[0]["choch_zone"] is None


# ---------------------------------------------------------------------------
# get_active_choch_zone
# ---------------------------------------------------------------------------


def test_get_active_choch_zone_returns_most_recent():
    # Three confirmed impulses — zone must be sourced from the third (legs[2]).
    legs = [
        _make_leg("impulse", 100, 80, 0, 5, True),   # first:  gets None
        _make_leg("impulse", 90, 70, 10, 15, True),  # second: prior=first (end=80), start=90
        _make_leg("impulse", 78, 60, 20, 25, True),  # third:  prior=second (end=70), start=78
    ]
    candles = [MockCandle(close=65.0)]
    result = get_active_choch_zone(legs, "down", candles)

    assert result is not None
    assert result["source_leg_index"] == 2
    # lower = min(78, 70) = 70, upper = max(78, 70) = 78
    assert result["choch_zone"]["lower_boundary"] == 70.0
    assert result["choch_zone"]["upper_boundary"] == 78.0
    assert result["current_price"] == 65.0


def test_get_active_choch_zone_returns_none_when_insufficient():
    legs = [_make_leg("impulse", 100, 80, 0, 5, True)]
    candles = [MockCandle(close=75.0)]
    result = get_active_choch_zone(legs, "down", candles)
    assert result is None


# ---------------------------------------------------------------------------
# Edge case: zero-width zone guard
# ---------------------------------------------------------------------------


def test_zone_width_zero_guard():
    # Both boundaries equal — degenerate case must not divide by zero.
    zone = {
        "lower_boundary": 80.0,
        "upper_boundary": 80.0,
        "zone_midpoint": 80.0,
        "zone_width_pct": 0.0,
        "trend_direction": "down",
        "source_impulse_start_index": 10,
        "source_impulse_end_index": 15,
        "prior_impulse_end_index": 5,
    }
    result = compute_choch_proximity(zone, 80.0)
    assert result["price_in_zone"] is True
    assert result["proximity_pct"] == 0.0
    assert result["price_above_zone"] is False
    assert result["price_below_zone"] is False
