"""Tests for the structural depth walker."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

from src.core.features import Candle
import src.core.structural_walker as walker_module
from src.core.structural_walker import find_response_move, walk_structure
from src.core.trend_id import identify_trend


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
        "min_momentum_ratio": 0.3,
        "use_dominance_filter": False,
        "min_dominance_ratio": 1.2,
    }


def _make_downtrend_with_retracement(n_candles: int = 200) -> Tuple[List[Candle], Dict[str, Any]]:
    """Create a deterministic downtrend with a confirmed retracement and internal structure."""
    prices: List[float] = []

    # Phase 1: 100 → 60 (41 candles)
    for i in range(41):
        prices.append(round(100.0 - i * 1.0, 2))

    # Phase 2: 60 → 82 (22 candles, +22pt — bigger retracement to make intermediate low score > abs low)
    for i in range(1, 23):
        prices.append(round(60.0 + i * 1.0, 2))  # 61, 62, ..., 82

    # Phase 3: 82 → 40 (43 candles)
    for i in range(1, 43):
        prices.append(round(82.0 - i * (42 / 42), 2))  # 81, 80, ..., 40

    # Phase 4: active retracement 40 → 55 → 47 → 60 (zigzag, 55 candles)
    # mini-up 1: 40 → 55 (20 candles)
    for i in range(1, 21):
        prices.append(round(40.0 + i * 0.75, 2))  # 40.75, ..., 55

    # mini-down 1: 55 → 47 (15 candles)
    for i in range(1, 16):
        prices.append(round(55.0 - i * (8 / 15), 2))

    # mini-up 2: 47 → 60 (20 candles)
    for i in range(1, 21):
        prices.append(round(47.0 + i * 0.65, 2))  # 47.65, ..., 60

    # Phase 5: 60 → 50 (20 candles) — makes the retracement confirmed
    for i in range(1, 21):
        prices.append(round(60.0 - i * 0.5, 2))

    # Extend with a smooth continuation impulse (no flat padding) to avoid micro-leg noise.
    while len(prices) < n_candles:
        prices.append(round(prices[-1] - 0.2, 2))
    prices = prices[:n_candles]

    candles = _make_candles(prices)
    result = identify_trend(candles, **_default_filter_config())
    return candles, result


# ---------------------------------------------------------------------------
# find_response_move
# ---------------------------------------------------------------------------


def test_find_response_move_returns_none_when_no_retracement_after_attempt():
    # RMT: one impulse (the Attempt), no subsequent retracement
    rmt_result = {
        "legs": [
            {
                "type": "impulse",
                "start_price": 40.0,
                "end_price": 55.0,
                "start_index": 0,
                "end_index": 20,
                "confirmed": True,
                "slope": 0.75,
            }
        ]
    }
    most_recent_attempt = {
        "leg_index": 0,
        "start_index": 0,
        "end_index": 20,
        "start_price": 40.0,
        "end_price": 55.0,
        "attempt_result": "pending",
    }
    result = find_response_move(rmt_result, most_recent_attempt, "down")
    assert result is None


def test_find_response_move_returns_next_confirmed_retracement():
    # RMT: impulse (Attempt at index 0) → retracement (Response Move at index 1) → impulse
    rmt_result = {
        "legs": [
            {
                "type": "impulse",
                "start_price": 40.0,
                "end_price": 55.0,
                "start_index": 0,
                "end_index": 20,
                "confirmed": True,
                "slope": 0.75,
            },
            {
                "type": "retracement",
                "start_price": 55.0,
                "end_price": 48.0,
                "start_index": 20,
                "end_index": 35,
                "confirmed": True,
                "slope": -0.47,
            },
            {
                "type": "impulse",
                "start_price": 48.0,
                "end_price": 60.0,
                "start_index": 35,
                "end_index": 54,
                "confirmed": True,
                "slope": 0.63,
            },
        ]
    }
    most_recent_attempt = {
        "leg_index": 0,
        "start_index": 0,
        "end_index": 20,
        "start_price": 40.0,
        "end_price": 55.0,
        "attempt_result": "false_break",
    }
    result = find_response_move(rmt_result, most_recent_attempt, "down")
    assert result is not None
    assert result["leg_index"] == 1
    assert result["start_price"] == 55.0
    assert result["end_price"] == 48.0


# ---------------------------------------------------------------------------
# walk_structure — non-walkable cases
# ---------------------------------------------------------------------------


def test_walk_structure_range_returns_not_walkable():
    candles = _make_candles([100.0] * 50)
    result = {
        "trend": "range",
        "trend_start": None,
        "legs": [],
        "current_phase": "unknown",
    }
    report = walk_structure(candles, result, _default_filter_config())
    assert report["walkable"] is False
    assert report["reason"] == "global_trend_is_range"


def test_walk_structure_no_retracement_returns_not_walkable():
    # Only impulse legs, no confirmed retracement
    candles = _make_candles([float(i) for i in range(100, 60, -1)] + [60.0] * 10)
    result = {
        "trend": "down",
        "trend_start": {"price": 100.0, "index": 0, "timestamp": None},
        "legs": [
            {
                "type": "impulse",
                "start_price": 100.0,
                "end_price": 60.0,
                "start_index": 0,
                "end_index": 39,
                "confirmed": True,
                "slope": -1.0,
            }
        ],
        "current_phase": "impulse",
    }
    report = walk_structure(candles, result, _default_filter_config())
    assert report["walkable"] is False
    assert report["reason"] == "no_confirmed_retracement"


# ---------------------------------------------------------------------------
# walk_structure — valid input
# ---------------------------------------------------------------------------


def test_walk_structure_returns_walkable_on_valid_input():
    candles, result = _make_downtrend_with_retracement()
    report = walk_structure(candles, result, _default_filter_config())
    assert report["walkable"] is True


def test_levels_list_non_empty():
    candles, result = _make_downtrend_with_retracement()
    report = walk_structure(candles, result, _default_filter_config())
    assert report["walkable"] is True
    assert len(report["levels"]) >= 1


def test_levels_depth_is_sequential():
    candles, result = _make_downtrend_with_retracement()
    report = walk_structure(candles, result, _default_filter_config())
    levels = report["levels"]
    for i, lvl in enumerate(levels):
        assert lvl["depth"] == i + 1, f"Level {i} has depth {lvl['depth']}, expected {i+1}"


def test_global_offset_stored_per_level():
    candles, result = _make_downtrend_with_retracement()
    report = walk_structure(candles, result, _default_filter_config())
    for lvl in report["levels"]:
        assert "global_offset" in lvl
        assert isinstance(lvl["global_offset"], int)
        assert lvl["global_offset"] >= 0


def test_termination_reason_present():
    candles, result = _make_downtrend_with_retracement()
    report = walk_structure(candles, result, _default_filter_config())
    deepest = report["levels"][-1]
    assert deepest.get("termination_reason") is not None


def test_total_mitigation_count_is_integer():
    candles, result = _make_downtrend_with_retracement()
    report = walk_structure(candles, result, _default_filter_config())
    assert isinstance(report["total_mitigation_count"], int)
    assert report["total_mitigation_count"] >= 0


def test_max_depth_respected():
    candles, result = _make_downtrend_with_retracement()
    report = walk_structure(candles, result, _default_filter_config(), max_depth=1)
    levels = report["levels"]
    assert len(levels) == 1
    valid_reasons = {
        "max_depth_reached",
        "no_attempt_found",
        "waiting_for_response_move",
        "child_slice_too_small",
        "invalid_analysis",
    }
    assert report["deepest_termination_reason"] in valid_reasons


def test_active_level_is_positive_integer():
    candles, result = _make_downtrend_with_retracement()
    report = walk_structure(candles, result, _default_filter_config())
    assert isinstance(report["active_level"], int)
    assert report["active_level"] >= 1


def test_waiting_for_is_non_empty_string():
    candles, result = _make_downtrend_with_retracement()
    report = walk_structure(candles, result, _default_filter_config())
    assert isinstance(report["waiting_for"], str)
    assert len(report["waiting_for"]) > 0


def test_stars_aligned_is_false():
    candles, result = _make_downtrend_with_retracement()
    report = walk_structure(candles, result, _default_filter_config())
    assert report["stars_aligned"] is False


def test_state_report_schema_complete():
    candles, result = _make_downtrend_with_retracement()
    report = walk_structure(candles, result, _default_filter_config())
    required_keys = {
        "walkable",
        "reason",
        "global_trend",
        "levels",
        "max_depth_reached",
        "total_mitigation_count",
        "deepest_termination_reason",
        "active_level",
        "active_choch_zone",
        "active_choch_proximity",
        "waiting_for",
        "stars_aligned",
    }
    for key in required_keys:
        assert key in report, f"Missing key: {key}"


def test_no_double_identify_trend_call():
    candles, result = _make_downtrend_with_retracement()

    counter = {"count": 0}
    original_identify_trend = walker_module.identify_trend

    def _counting_identify_trend(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        counter["count"] += 1
        return original_identify_trend(*args, **kwargs)

    walker_module.identify_trend = _counting_identify_trend
    try:
        report = walk_structure(candles, result, _default_filter_config(), max_depth=4)
    finally:
        walker_module.identify_trend = original_identify_trend

    assert counter["count"] == len(report["levels"])


# ---------------------------------------------------------------------------
# New fields: layer_start_index, layer_end_index, rmt_result
# ---------------------------------------------------------------------------


def test_layer_start_index_is_global():
    candles, result = _make_downtrend_with_retracement()
    state = walk_structure(candles, result, _default_filter_config())
    if state["walkable"] and state["levels"]:
        level = state["levels"][0]
        assert "layer_start_index" in level
        assert isinstance(level["layer_start_index"], int)
        assert level["layer_start_index"] >= 0
        assert level["layer_start_index"] < len(candles)
        # Verify it is a global index — should match retracement leg start + global offset
        assert level["layer_start_index"] == level["global_offset"] + level["retracement_leg"]["start_index"]


def test_rmt_result_present_in_each_level():
    candles, result = _make_downtrend_with_retracement()
    state = walk_structure(candles, result, _default_filter_config())
    if state["walkable"]:
        for level in state["levels"]:
            assert "rmt_result" in level
            if level["rmt_result"] is not None:
                assert "legs" in level["rmt_result"]
                assert "trend" in level["rmt_result"]
