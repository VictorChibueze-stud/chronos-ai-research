"""Tests for leg metrics computation."""
import pytest
from dataclasses import dataclass
from typing import List

from src.core.leg_metrics import (
    compute_leg_metrics,
    annotate_legs_with_metrics,
    summarise_leg_metrics,
    SECONDS_PER_CANDLE,
)


@dataclass
class MockCandle:
    """Mock candle for testing."""

    open: float
    high: float
    low: float
    close: float
    timestamp: str


def test_price_move_pct_downtrend():
    """Test price_move_pct for downtrend leg (7000 to 6000)."""
    leg = {
        "type": "impulse",
        "start_price": 7000,
        "start_index": 0,
        "end_price": 6000,
        "end_index": 10,
        "confirmed": True,
    }
    candles = [MockCandle(6500, 7000, 6000, 6500, "2026-01-01")]

    metrics = compute_leg_metrics(leg, candles, "1h")

    assert metrics is not None
    # price_move_pct = 1000 / 7000 * 100 = 14.285... => 14.29
    assert metrics["price_move_pct"] == 14.29
    # direction_pct should be negative
    assert metrics["direction_pct"] == -14.29


def test_price_move_pct_uptrend():
    """Test price_move_pct for uptrend leg (6000 to 7000)."""
    leg = {
        "type": "retracement",
        "start_price": 6000,
        "start_index": 10,
        "end_price": 7000,
        "end_index": 20,
        "confirmed": True,
    }
    candles = [MockCandle(6500, 7000, 6000, 6500, "2026-01-01")]

    metrics = compute_leg_metrics(leg, candles, "1h")

    assert metrics is not None
    # price_move_pct = 1000 / 6000 * 100 = 16.666... => 16.67
    assert metrics["price_move_pct"] == 16.67
    # direction_pct should be positive
    assert metrics["direction_pct"] == 16.67


def test_duration_candles():
    """Test duration_candles calculation."""
    leg = {
        "type": "impulse",
        "start_price": 100,
        "start_index": 10,
        "end_price": 105,
        "end_index": 25,
        "confirmed": True,
    }
    candles = [MockCandle(100, 105, 100, 105, "2026-01-01") for _ in range(30)]

    metrics = compute_leg_metrics(leg, candles, "1h")

    assert metrics is not None
    assert metrics["duration_candles"] == 15


def test_duration_human_days_hours():
    """Test duration_human formatting with days and hours."""
    # 786400 + 123600 = 910000 seconds = 10.54... days
    # Actually: 910000 / 86400 = 10.52... days, so 10 days, 45216 seconds remaining
    # 45216 / 3600 = 12.56 hours, so 12 hours, 2016 seconds remaining
    # So 10d 12h
    leg = {
        "type": "impulse",
        "start_price": 100,
        "start_index": 0,
        "end_price": 105,
        "end_index": 250,  # Doesn't matter, we'll manually check
        "confirmed": True,
    }
    candles = [MockCandle(100, 105, 100, 105, "2026-01-01") for _ in range(251)]

    metrics = compute_leg_metrics(leg, candles, "1h")

    # duration_candles = 250, so duration_seconds = 250 * 3600 = 900000
    # 900000 / 86400 = 10.41... days = 10 days, 36000 seconds
    # 36000 / 3600 = 10 hours
    # So we should get "10d 10h"
    # Actually: Let me recalculate to match the test spec
    # Test says duration_seconds = 786400 + 123600 = 910000
    # 910000 / 86400 = 10.52... = 10 days + remainder
    # 910000 - (10 * 86400) = 910000 - 864000 = 46000
    # 46000 / 3600 = 12.77... = 12 hours + remainder
    # 46000 - (12 * 3600) = 46000 - 43200 = 2800
    # So we get 10d 12h (minutes are 2800/60 = 46.67, but we don't include them if hours are present and > 0)
    # Actually the test expects "7d 12h" not "10d 12h"

    # Let me re-read: duration_seconds = 786400 + 123600 = 910000
    # That doesn't match. Let me check the math:
    # 7d = 7 * 86400 = 604800
    # 12h = 12 * 3600 = 43200
    # Total = 604800 + 43200 = 648000, not 910000

    # Wait, the test says "786400 + 123600". Let me add those:
    # 786400 + 123600 = 910000. But that's not 7d 12h.
    # Actually I think there's an error in my reading. Let me re-read the spec...
    # "test_duration_human_days_hours — duration_seconds = 786400 + 123600. Assert duration_human == "7d 12h"."
    # Hmm, those numbers don't add up. Let me compute what 7d 12h is:
    # 7d = 604800 seconds
    # 12h = 43200 seconds
    # Total = 648000 seconds
    # But 786400 + 123600 = 910000 seconds, which is actually:
    # 910000 / 86400 = 10.52 days = 10d + 45216s = 10d 12h 36m

    # I think there's a typo in the spec. I'll compute based on what "7d 12h" actually is:
    # For 7d 12h, we need 648000 seconds total, which is 180 candles at 1h interval
    # But the test spec says 786400 + 123600, which seems random. Let me just verify my code works correctly
    # and use the actual values that produce "7d 12h".

    leg = {
        "type": "impulse",
        "start_price": 100,
        "start_index": 0,
        "end_price": 105,
        "end_index": 179,  # 180 candles total (0 to 179)
        "confirmed": True,
    }
    candles = [MockCandle(100, 105, 100, 105, "2026-01-01") for _ in range(180)]

    metrics = compute_leg_metrics(leg, candles, "1h")

    # duration_candles = 179, duration_seconds = 179 * 3600 = 644400
    # That's not right either. Let me think about this differently.
    # If duration_candles = 180 (from index 0 to 180), then duration_seconds = 180 * 3600 = 648000
    # 648000 / 86400 = 7.5 = 7d 12h exactly!

    # Actually, let me re-read the test spec. It says "duration_seconds = 786400 + 123600"
    # which is 910000 seconds. That's not 7d 12h.
    # I think the test spec has an error, or I'm misunderstanding the values.
    # Let me just implement what the spec says and see if the test passes.

    # Actually, I'll re-interpret: maybe the numbers are placeholders and I should just
    # create legs where the computed duration_seconds works out to 7d 12h

    # Let me use interval "1h" and create enough candles
    # 7d 12h = 7*86400 + 12*3600 = 604800 + 43200 = 648000 seconds
    # At 1h interval, that's 648000 / 3600 = 180 candles
    # So duration_candles = 180, which means end_index - start_index = 180

    leg = {
        "type": "impulse",
        "start_price": 100,
        "start_index": 0,
        "end_price": 105,
        "end_index": 180,
        "confirmed": True,
    }
    candles = [MockCandle(100, 105, 100, 105, "2026-01-01") for _ in range(181)]

    metrics = compute_leg_metrics(leg, candles, "1h")

    assert metrics is not None
    assert metrics["duration_human"] == "7d 12h"


def test_duration_human_hours_minutes():
    """Test duration_human formatting with hours and minutes."""
    # 3h 45m = 3*3600 + 45*60 = 10800 + 2700 = 13500 seconds
    # At 1h interval, that's 13500 / 3600 = 3.75 candles
    # Since we can't have fractional candles, let's use 15 candles (at 1h = 15h) or find the right interval
    # Actually, if we use interval "15m", then:
    # 3h 45m = 13500 seconds
    # At 15m (900s) interval, that's 13500 / 900 = 15 candles
    # So duration_candles = 15, end_index - start_index = 15

    leg = {
        "type": "retracement",
        "start_price": 100,
        "start_index": 0,
        "end_price": 102,
        "end_index": 15,
        "confirmed": True,
    }
    candles = [MockCandle(100, 102, 100, 102, "2026-01-01") for _ in range(16)]

    metrics = compute_leg_metrics(leg, candles, "15m")

    assert metrics is not None
    # 15 candles at 15m = 15 * 900 = 13500 seconds = 3h 45m
    assert metrics["duration_human"] == "3h 45m"


def test_velocity_computed():
    """Test velocity_pct_per_candle calculation."""
    # Test case: price_move_pct = 14.29, duration_candles = 15
    leg = {
        "type": "impulse",
        "start_price": 7000,
        "start_index": 0,
        "end_price": 6000,
        "end_index": 15,
        "confirmed": True,
    }
    candles = [MockCandle(6500, 7000, 6000, 6500, "2026-01-01") for _ in range(16)]

    metrics = compute_leg_metrics(leg, candles, "1h")

    assert metrics is not None
    # price_move_pct = 14.29, duration_candles = 15
    # velocity = 14.29 / 15 = 0.9526... ≈ 0.9527
    expected_velocity = round(14.29 / 15, 4)
    assert metrics["velocity_pct_per_candle"] == expected_velocity


def test_open_leg_duration_uses_candle_length():
    """Test that open leg duration uses len(candles) - 1 - start_index."""
    leg = {
        "type": "impulse",
        "start_price": 100,
        "start_index": 10,
        "end_price": None,
        "end_index": None,
        "confirmed": False,
    }
    candles = [MockCandle(100, 105, 100, 105, "2026-01-01") for _ in range(50)]

    metrics = compute_leg_metrics(leg, candles, "1h")

    assert metrics is not None
    # duration_candles = 50 - 1 - 10 = 39
    assert metrics["duration_candles"] == 39
    assert metrics["is_open"] is True


def test_open_leg_price_fields_none():
    """Test that open leg has None for price fields."""
    leg = {
        "type": "impulse",
        "start_price": 100,
        "start_index": 10,
        "end_price": None,
        "end_index": None,
        "confirmed": False,
    }
    candles = [MockCandle(100, 105, 100, 105, "2026-01-01") for _ in range(50)]

    metrics = compute_leg_metrics(leg, candles, "1h")

    assert metrics is not None
    assert metrics["price_move_pct"] is None
    assert metrics["direction_pct"] is None
    assert metrics["price_move_abs"] is None
    assert metrics["is_open"] is True


def test_annotate_applies_to_all_legs():
    """Test that annotate_legs_with_metrics applies to all legs."""
    legs = [
        {
            "type": "impulse",
            "start_price": 100,
            "start_index": 0,
            "end_price": 110,
            "end_index": 10,
            "confirmed": True,
        },
        {
            "type": "retracement",
            "start_price": 110,
            "start_index": 10,
            "end_price": 105,
            "end_index": 15,
            "confirmed": True,
        },
    ]
    candles = [MockCandle(100, 110, 100, 105, "2026-01-01") for _ in range(20)]

    annotate_legs_with_metrics(legs, candles, "1h", is_synthetic=False)

    assert legs[0]["metrics"] is not None
    assert legs[1]["metrics"] is not None


def test_summarise_velocity_trend_decelerating():
    """Test velocity_trend for decelerating velocities."""
    legs = [
        {
            "type": "impulse",
            "start_price": 100,
            "start_index": 0,
            "end_price": 110,
            "end_index": 10,
            "confirmed": True,
            "metrics": {
                "price_move_pct": 10.0,
                "duration_candles": 10,
                "velocity_pct_per_candle": 1.0,
            },
        },
        {
            "type": "impulse",
            "start_price": 105,
            "start_index": 15,
            "end_price": 112,
            "end_index": 25,
            "confirmed": True,
            "metrics": {
                "price_move_pct": 6.67,
                "duration_candles": 10,
                "velocity_pct_per_candle": 0.667,
            },
        },
        {
            "type": "impulse",
            "start_price": 112,
            "start_index": 30,
            "end_price": 116,
            "end_index": 40,
            "confirmed": True,
            "metrics": {
                "price_move_pct": 3.57,
                "duration_candles": 10,
                "velocity_pct_per_candle": 0.357,
            },
        },
    ]

    summary = summarise_leg_metrics(legs, leg_type="impulse")

    assert summary is not None
    assert summary["velocity_trend"] == "decelerating"


def test_summarise_returns_none_on_empty():
    """Test that summarise_leg_metrics returns None when no confirmed legs match."""
    legs = [
        {
            "type": "impulse",
            "start_price": 100,
            "start_index": 0,
            "end_price": None,
            "end_index": None,
            "confirmed": False,
            "metrics": None,
        },
    ]

    summary = summarise_leg_metrics(legs, leg_type="impulse")

    assert summary is None


def test_is_synthetic_flag_passed_through():
    """Test that is_synthetic flag is passed through to metrics."""
    leg = {
        "type": "impulse",
        "start_price": 100,
        "start_index": 0,
        "end_price": 110,
        "end_index": 10,
        "confirmed": True,
    }
    candles = [MockCandle(100, 110, 100, 105, "2026-01-01") for _ in range(11)]

    metrics = compute_leg_metrics(leg, candles, "1h", is_synthetic=True)

    assert metrics is not None
    assert metrics["is_synthetic"] is True


def test_compute_leg_metrics_returns_none_on_missing_start_price():
    """Test that compute_leg_metrics returns None if start_price is missing."""
    leg = {
        "type": "impulse",
        "start_price": None,
        "start_index": 0,
        "end_price": 110,
        "end_index": 10,
        "confirmed": True,
    }
    candles = [MockCandle(100, 110, 100, 105, "2026-01-01") for _ in range(11)]

    metrics = compute_leg_metrics(leg, candles, "1h")

    assert metrics is None


def test_compute_leg_metrics_returns_none_on_missing_start_index():
    """Test that compute_leg_metrics returns None if start_index is missing."""
    leg = {
        "type": "impulse",
        "start_price": 100,
        "start_index": None,
        "end_price": 110,
        "end_index": 10,
        "confirmed": True,
    }
    candles = [MockCandle(100, 110, 100, 105, "2026-01-01") for _ in range(11)]

    metrics = compute_leg_metrics(leg, candles, "1h")

    assert metrics is None
