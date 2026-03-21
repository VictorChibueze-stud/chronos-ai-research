"""Tests for retracement analysis (RMT, structural level, attempts)."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pytest

from src.core.features import Candle
from src.core.retracement_analysis import (
    analyze_current_retracement,
    analyze_retracement_leg,
    find_attempts,
    find_rmt_structural_level,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candles(prices: List[float]) -> List[Candle]:
    base = datetime(2024, 1, 1)
    return [
        Candle(
            timestamp=base + timedelta(hours=i),
            open=price,
            high=price * 1.001,
            low=price * 0.999,
            close=price,
            volume=100.0,
        )
        for i, price in enumerate(prices)
    ]


def _default_filter_config() -> Dict[str, Any]:
    return {
        "use_parent_relative_filter": False,
        "min_impulse_parent_ratio": 0.15,
        "use_momentum_filter": False,
        "min_momentum_ratio": 0.5,
        "use_dominance_filter": False,
        "min_dominance_ratio": 1.5,
    }


def _make_impulse(
    start_price: float,
    end_price: float,
    start_index: int,
    end_index: int,
    confirmed: bool = True,
) -> Dict[str, Any]:
    return {
        "type": "impulse",
        "start_price": start_price,
        "end_price": end_price,
        "start_index": start_index,
        "end_index": end_index,
        "confirmed": confirmed,
        "slope": None,
    }


def _make_retracement(
    start_price: float,
    end_price: float,
    start_index: int,
    end_index: int,
    confirmed: bool = True,
) -> Dict[str, Any]:
    return {
        "type": "retracement",
        "start_price": start_price,
        "end_price": end_price,
        "start_index": start_index,
        "end_index": end_index,
        "confirmed": confirmed,
        "slope": None,
    }


def _zigzag_down_prices(n: int = 50, start: float = 100.0) -> List[float]:
    """50-candle downward zigzag: 7 candles down 1pt, 3 candles up 0.5pt per cycle."""
    prices = []
    price = start
    for i in range(n):
        if i % 10 < 7:
            price -= 1.0
        else:
            price += 0.5
        prices.append(round(price, 2))
    return prices


# ---------------------------------------------------------------------------
# find_rmt_structural_level
# ---------------------------------------------------------------------------


def test_find_structural_level_downtrend():
    # Global downtrend → retracement goes UP → structural level = highest end_price
    # leg 0: ends at 90, leg 1: ends at 95 → max = 95
    rmt_result = {
        "trend": "up",
        "legs": [
            _make_impulse(80, 90, 0, 5),
            _make_impulse(85, 95, 8, 12),
        ],
    }
    result = find_rmt_structural_level(rmt_result, global_trend="down")
    assert result is not None
    assert result["price"] == 95.0
    assert result["source_leg_index"] == 1


def test_find_structural_level_uptrend():
    # Global uptrend → retracement goes DOWN → structural level = lowest end_price
    # leg 0: ends at 80, leg 1: ends at 75 → min = 75
    rmt_result = {
        "trend": "down",
        "legs": [
            _make_impulse(90, 80, 0, 5),
            _make_impulse(85, 75, 8, 12),
        ],
    }
    result = find_rmt_structural_level(rmt_result, global_trend="up")
    assert result is not None
    assert result["price"] == 75.0
    assert result["source_leg_index"] == 1


def test_find_structural_level_no_impulses():
    rmt_result = {
        "trend": "up",
        "legs": [
            _make_retracement(95, 90, 5, 8),
        ],
    }
    result = find_rmt_structural_level(rmt_result, global_trend="down")
    assert result is None


# ---------------------------------------------------------------------------
# find_attempts
# ---------------------------------------------------------------------------


def test_find_attempts_empty_when_no_impulse_reaches_level():
    # Structural level at 100; all impulse legs end below 100
    rmt_result = {
        "trend": "up",
        "legs": [
            _make_impulse(80, 90, 0, 5),
            _make_retracement(90, 85, 5, 8),
            _make_impulse(85, 92, 8, 13),
        ],
    }
    structural_level = {"price": 100.0, "source_leg_index": 2, "source_leg_end_index": 13}
    attempts = find_attempts(rmt_result, structural_level, "down")
    assert attempts == []


def test_find_attempts_detects_false_break():
    # Impulse ends at 102 (>= 100); next retracement ends at 95 (< 100) → false_break
    rmt_result = {
        "trend": "up",
        "legs": [
            _make_impulse(90, 102, 0, 5),
            _make_retracement(102, 95, 5, 8),
        ],
    }
    structural_level = {"price": 100.0, "source_leg_index": 0, "source_leg_end_index": 5}
    attempts = find_attempts(rmt_result, structural_level, "down")
    assert len(attempts) == 1
    assert attempts[0]["attempt_result"] == "false_break"


def test_find_attempts_detects_real_break():
    # Impulse ends at 102 (>= 100); next retracement ends at 101 (>= 100) → real_break
    rmt_result = {
        "trend": "up",
        "legs": [
            _make_impulse(90, 102, 0, 5),
            _make_retracement(102, 101, 5, 8),
        ],
    }
    structural_level = {"price": 100.0, "source_leg_index": 0, "source_leg_end_index": 5}
    attempts = find_attempts(rmt_result, structural_level, "down")
    assert len(attempts) == 1
    assert attempts[0]["attempt_result"] == "real_break"


def test_find_attempts_pending_when_no_next_retracement():
    # Impulse ends at 102 with no subsequent retracement → pending
    rmt_result = {
        "trend": "up",
        "legs": [
            _make_impulse(90, 102, 0, 5),
        ],
    }
    structural_level = {"price": 100.0, "source_leg_index": 0, "source_leg_end_index": 5}
    attempts = find_attempts(rmt_result, structural_level, "down")
    assert len(attempts) == 1
    assert attempts[0]["attempt_result"] == "pending"


def test_find_attempts_multiple_returns_all():
    # Three impulse legs all ending at 102 (== structural level 102)
    # Results: false_break, real_break, pending
    rmt_result = {
        "trend": "up",
        "legs": [
            _make_impulse(90, 102, 0, 5),       # attempt 1
            _make_retracement(102, 97, 5, 8),   # next_end=97 < 102 → false_break
            _make_impulse(97, 102, 8, 13),      # attempt 2
            _make_retracement(102, 103, 13, 16), # next_end=103 >= 102 → real_break
            _make_impulse(103, 102, 16, 21),    # attempt 3 (no next retracement) → pending
        ],
    }
    structural_level = {"price": 102.0, "source_leg_index": 0, "source_leg_end_index": 5}
    attempts = find_attempts(rmt_result, structural_level, "down")
    assert len(attempts) == 3
    assert attempts[0]["attempt_result"] == "false_break"
    assert attempts[1]["attempt_result"] == "real_break"
    assert attempts[2]["attempt_result"] == "pending"
    # Most recent is last
    assert attempts[-1]["leg_index"] == 4


# ---------------------------------------------------------------------------
# analyze_retracement_leg
# ---------------------------------------------------------------------------


def test_analyze_retracement_leg_too_small():
    candles = _make_candles([100.0] * 10)
    leg = _make_retracement(100.0, 95.0, 0, 4)  # only 5 candles in slice
    result = analyze_retracement_leg(leg, candles, "up", _default_filter_config())
    assert result is None


def test_analyze_retracement_leg_unconfirmed():
    candles = _make_candles([100.0] * 50)
    leg = _make_retracement(100.0, 95.0, 0, 49, confirmed=False)
    result = analyze_retracement_leg(leg, candles, "up", _default_filter_config())
    assert result is None


def test_analyze_retracement_leg_range():
    # Prices barely move (< 3% range) → identify_trend returns "range"
    flat_prices = [100.0 + (i % 3) * 0.1 for i in range(20)]
    candles = _make_candles(flat_prices)
    leg = _make_retracement(flat_prices[0], flat_prices[-1], 0, 19)
    result = analyze_retracement_leg(leg, candles, "up", _default_filter_config())
    assert result is not None
    assert result["analysis_valid"] is False
    assert result["rmt_trend"] == "range"


def test_analyze_retracement_leg_valid():
    # 50-candle downward zigzag — simulates a retracement in a global uptrend
    prices = _zigzag_down_prices(50)
    candles = _make_candles(prices)
    leg = _make_retracement(prices[0], prices[-1], 0, 49)
    result = analyze_retracement_leg(leg, candles, "up", _default_filter_config())
    assert result is not None
    assert result["analysis_valid"] is True
    assert result["rmt_leg_count"] >= 1
    assert result["slice_candle_count"] == 50


def test_mitigation_count_zero_when_no_false_breaks():
    # No impulse legs reach the structural level → zero attempts → zero mitigations
    rmt_result = {
        "trend": "up",
        "legs": [
            _make_impulse(80, 88, 0, 5),
            _make_retracement(88, 84, 5, 8),
            _make_impulse(84, 90, 8, 13),
        ],
    }
    structural_level = {"price": 100.0, "source_leg_index": 2, "source_leg_end_index": 13}
    attempts = find_attempts(rmt_result, structural_level, "down")
    mitigation_count = sum(1 for a in attempts if a["attempt_result"] == "false_break")
    assert mitigation_count == 0


def test_mitigation_count_increments_per_false_break():
    # Two impulse legs both reach structural level 100; both followed by retracements < 100
    rmt_result = {
        "trend": "up",
        "legs": [
            _make_impulse(90, 102, 0, 5),
            _make_retracement(102, 95, 5, 8),   # 95 < 100 → false_break
            _make_impulse(95, 102, 8, 13),
            _make_retracement(102, 96, 13, 16),  # 96 < 100 → false_break
        ],
    }
    structural_level = {"price": 100.0, "source_leg_index": 0, "source_leg_end_index": 5}
    attempts = find_attempts(rmt_result, structural_level, "down")
    mitigation_count = sum(1 for a in attempts if a["attempt_result"] == "false_break")
    assert mitigation_count == 2


# ---------------------------------------------------------------------------
# analyze_current_retracement
# ---------------------------------------------------------------------------


def test_analyze_current_retracement_returns_none_when_no_retracement():
    candles = _make_candles([100.0] * 20)
    result = {
        "trend": "down",
        "legs": [
            _make_impulse(100, 85, 0, 10),
            _make_impulse(85, 70, 11, 19),
        ],
        "current_phase": "impulse",
    }
    assert analyze_current_retracement(candles, result, _default_filter_config()) is None


def test_analyze_current_retracement_uses_most_recent():
    # Two confirmed retracement legs; the second must be used
    # second retracement spans 20 candles (indices 30-49) → 20-candle slice ≥ 10 → not None
    prices = [100.0] * 50
    candles = _make_candles(prices)

    ret_1 = _make_retracement(95, 98, 5, 15)   # 11 candles
    ret_2 = _make_retracement(90, 93, 30, 49)  # 20 candles

    result = {
        "trend": "down",
        "legs": [
            _make_impulse(100, 95, 0, 4),
            ret_1,
            _make_impulse(98, 90, 16, 29),
            ret_2,
        ],
        "current_phase": "retracement",
    }

    analysis = analyze_current_retracement(candles, result, _default_filter_config())
    assert analysis is not None
    assert analysis["slice_start_index"] == ret_2["start_index"]


# ---------------------------------------------------------------------------
# test_filter_config_passed_through
# ---------------------------------------------------------------------------


def test_filter_config_passed_through():
    # Call with momentum filter enabled and a high ratio; must not raise
    prices = _zigzag_down_prices(50)
    candles = _make_candles(prices)
    leg = _make_retracement(prices[0], prices[-1], 0, 49)

    strict_config = {
        "use_parent_relative_filter": False,
        "min_impulse_parent_ratio": 0.15,
        "use_momentum_filter": True,
        "min_momentum_ratio": 2.0,
        "use_dominance_filter": False,
        "min_dominance_ratio": 1.5,
    }

    result = analyze_retracement_leg(leg, candles, "up", strict_config)
    # Must return a dict (valid or invalid) without raising
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# test_output_schema_completeness
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = {
    "rmt_trend",
    "structural_level",
    "attempts",
    "attempt_count",
    "most_recent_attempt",
    "most_recent_attempt_result",
    "mitigation_count",
    "rmt_choch_zone",
    "rmt_choch_proximity",
    "slice_start_index",
    "slice_end_index",
    "slice_candle_count",
    "analysis_valid",
}


def test_output_schema_completeness():
    prices = _zigzag_down_prices(50)
    candles = _make_candles(prices)
    leg = _make_retracement(prices[0], prices[-1], 0, 49)
    result = analyze_retracement_leg(leg, candles, "up", _default_filter_config())
    assert result is not None
    for key in _REQUIRED_KEYS:
        assert key in result, f"Missing key: {key}"
