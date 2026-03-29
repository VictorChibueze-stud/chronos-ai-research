"""Tests for the structural depth walker."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

import src.core.structural_walker as walker_module
from src.core.features import Candle
from src.core.structural_walker import find_crossing_attempt, serialize_state_report, walk_structure
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
        "min_momentum_ratio": 0.5,
        "use_dominance_filter": False,
        "min_dominance_ratio": 1.5,
    }


def _make_downtrend_with_retracement(n_candles: int = 200) -> Tuple[List[Candle], Dict[str, Any]]:
    """Deterministic downtrend with 2 confirmed impulses and active retracement."""
    prices: List[float] = []

    for i in range(41):
        prices.append(round(100.0 - i * 1.0, 2))
    for i in range(1, 23):
        prices.append(round(60.0 + i * 1.0, 2))
    for i in range(1, 43):
        prices.append(round(82.0 - i * (42 / 42), 2))
    for i in range(1, 21):
        prices.append(round(40.0 + i * 0.75, 2))
    for i in range(1, 16):
        prices.append(round(55.0 - i * (8 / 15), 2))
    for i in range(1, 21):
        prices.append(round(47.0 + i * 0.65, 2))
    for i in range(1, 21):
        prices.append(round(60.0 - i * 0.5, 2))

    while len(prices) < n_candles:
        prices.append(round(prices[-1] - 0.2, 2))
    prices = prices[:n_candles]

    candles = _make_candles(prices)
    result = identify_trend(candles, **_default_filter_config())
    return candles, result


def _mock_rmt_with_structure() -> Dict[str, Any]:
    """RMT with confirmed impulses so structural level + CHoCH are computable."""
    return {
        "trend": "up",
        "legs": [
            {"type": "impulse", "start_price": 90.0, "end_price": 98.0, "start_index": 0, "end_index": 5, "confirmed": True},
            {"type": "retracement", "start_price": 98.0, "end_price": 94.0, "start_index": 5, "end_index": 8, "confirmed": True},
            {"type": "impulse", "start_price": 94.0, "end_price": 104.0, "start_index": 8, "end_index": 15, "confirmed": True},
            {"type": "retracement", "start_price": 104.0, "end_price": 99.0, "start_index": 15, "end_index": 19, "confirmed": True},
            {"type": "impulse", "start_price": 99.0, "end_price": 108.0, "start_index": 19, "end_index": 28, "confirmed": True},
        ],
        "current_phase": "impulse",
    }


def _force_first_move(monkeypatch, offset: int = 5, price: float = 98.0) -> None:
    """Force _walk_level to pick a deterministic first move endpoint."""

    def _collect(candles, from_index, _direction, min_swing_candles):
        _ = min_swing_candles
        idx = min(from_index + offset, len(candles) - 2)
        return [{"price": price, "index": idx, "timestamp": candles[idx].timestamp}]

    def _score(_candles, candidates, _direction):
        return [{**candidate, "score": 1.0} for candidate in candidates]

    monkeypatch.setattr(walker_module, "_collect_candidates", _collect)
    monkeypatch.setattr(walker_module, "_score_candidates", _score)


# ---------------------------------------------------------------------------
# walk_structure
# ---------------------------------------------------------------------------


def test_walk_structure_range_returns_not_walkable():
    candles = _make_candles([100.0] * 50)
    result = {"trend": "range", "trend_start": None, "legs": [], "current_phase": "unknown"}
    report = walk_structure(candles, result, _default_filter_config())
    assert report["walkable"] is False


def test_walk_structure_no_retracement_returns_not_walkable():
    candles = _make_candles([float(i) for i in range(100, 60, -1)] + [60.0] * 12)
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


def test_walk_structure_returns_walkable_on_valid_input():
    candles, result = _make_downtrend_with_retracement()
    report = walk_structure(candles, result, _default_filter_config())
    assert report["walkable"] is True


def test_levels_list_non_empty():
    candles, result = _make_downtrend_with_retracement()
    report = walk_structure(candles, result, _default_filter_config())
    assert len(report["levels"]) >= 1


def test_depth_1_slice_matches_retracement_leg():
    candles, result = _make_downtrend_with_retracement()
    report = walk_structure(candles, result, _default_filter_config())
    confirmed_retracements = [
        leg for leg in result["legs"]
        if leg.get("type") == "retracement" and leg.get("confirmed") is True
    ]
    assert confirmed_retracements
    retracement_leg = confirmed_retracements[-1]
    assert report["levels"][0]["slice_start"] == int(retracement_leg["start_index"])
    assert report["levels"][0]["first_impulse"] is not None


def test_structural_level_present_when_rmt_has_impulse(monkeypatch):
    candles, result = _make_downtrend_with_retracement()

    _force_first_move(monkeypatch, offset=5, price=98.0)
    monkeypatch.setattr(walker_module, "identify_trend", lambda *_args, **_kwargs: _mock_rmt_with_structure())
    monkeypatch.setattr(walker_module, "find_crossing_attempt", lambda *_args, **_kwargs: None)

    report = walk_structure(candles, result, _default_filter_config())
    assert report["levels"][0]["structural_level"] is not None
    assert report["levels"][0]["structural_level"]["price"] == 98.0


def test_no_structural_level_when_rmt_has_no_impulse(monkeypatch):
    candles, result = _make_downtrend_with_retracement()

    monkeypatch.setattr(walker_module, "_collect_candidates", lambda *_args, **_kwargs: [])

    report = walk_structure(candles, result, _default_filter_config())
    assert report["levels"][0]["termination_reason"] == "no_structural_level"


def test_choch_mitigated_false_when_no_crossing(monkeypatch):
    candles, result = _make_downtrend_with_retracement()

    _force_first_move(monkeypatch, offset=5, price=98.0)
    monkeypatch.setattr(walker_module, "identify_trend", lambda *_args, **_kwargs: _mock_rmt_with_structure())
    monkeypatch.setattr(walker_module, "find_crossing_attempt", lambda *_args, **_kwargs: None)

    report = walk_structure(candles, result, _default_filter_config())
    assert report["levels"][0]["choch_mitigated"] is False


def test_choch_mitigated_true_when_crossing_found(monkeypatch):
    candles, result = _make_downtrend_with_retracement()

    _force_first_move(monkeypatch, offset=5, price=98.0)
    monkeypatch.setattr(walker_module, "identify_trend", lambda *_args, **_kwargs: _mock_rmt_with_structure())
    monkeypatch.setattr(
        walker_module,
        "find_crossing_attempt",
        lambda *_args, **_kwargs: {
            "leg_index": 2,
            "start_index": 8,
            "end_index": 20,
            "start_price": 94.0,
            "end_price": 108.0,
            "global_start_index": 100,
            "global_end_index": 120,
            "choch_zone": {"lower_boundary": 92.0, "upper_boundary": 96.0},
        },
    )

    report = walk_structure(candles, result, _default_filter_config(), max_depth=1)
    assert report["levels"][0]["choch_mitigated"] is True


def test_depth_advances_when_crossing_found(monkeypatch):
    candles, result = _make_downtrend_with_retracement()

    _force_first_move(monkeypatch, offset=5, price=98.0)
    monkeypatch.setattr(walker_module, "identify_trend", lambda *_args, **_kwargs: _mock_rmt_with_structure())

    calls = {"n": 0}

    def _attempt(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "leg_index": 2,
                "start_index": 8,
                "end_index": 24,
                "start_price": 94.0,
                "end_price": 108.0,
                "global_start_index": 100,
                "global_end_index": 124,
                "choch_zone": {"lower_boundary": 92.0, "upper_boundary": 96.0},
            }
        return None

    monkeypatch.setattr(walker_module, "find_crossing_attempt", _attempt)

    report = walk_structure(candles, result, _default_filter_config(), max_depth=4)
    assert len(report["levels"]) >= 2
    assert report["levels"][1]["depth"] == 2


def test_depth_does_not_advance_without_crossing(monkeypatch):
    candles, result = _make_downtrend_with_retracement()

    _force_first_move(monkeypatch, offset=5, price=98.0)
    monkeypatch.setattr(walker_module, "identify_trend", lambda *_args, **_kwargs: _mock_rmt_with_structure())
    monkeypatch.setattr(walker_module, "find_crossing_attempt", lambda *_args, **_kwargs: None)

    report = walk_structure(candles, result, _default_filter_config(), max_depth=4)
    assert len(report["levels"]) == 1


def test_max_depth_respected(monkeypatch):
    candles, result = _make_downtrend_with_retracement()

    _force_first_move(monkeypatch, offset=5, price=98.0)
    monkeypatch.setattr(walker_module, "identify_trend", lambda *_args, **_kwargs: _mock_rmt_with_structure())
    monkeypatch.setattr(
        walker_module,
        "find_crossing_attempt",
        lambda *_args, **_kwargs: {
            "leg_index": 2,
            "start_index": 8,
            "end_index": 24,
            "start_price": 94.0,
            "end_price": 108.0,
            "global_start_index": 100,
            "global_end_index": 124,
            "choch_zone": {"lower_boundary": 92.0, "upper_boundary": 96.0},
        },
    )

    report = walk_structure(candles, result, _default_filter_config(), max_depth=1)
    assert len(report["levels"]) == 1
    assert report["deepest_termination_reason"] in {"max_depth_reached", "no_crossing_attempt", "no_choch_zone", "no_structural_level", "slice_too_small"}


def test_total_mitigation_count_correct(monkeypatch):
    candles, result = _make_downtrend_with_retracement()

    _force_first_move(monkeypatch, offset=5, price=98.0)
    monkeypatch.setattr(walker_module, "identify_trend", lambda *_args, **_kwargs: _mock_rmt_with_structure())

    calls = {"n": 0}

    def _attempt(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "leg_index": 2,
                "start_index": 8,
                "end_index": 24,
                "start_price": 94.0,
                "end_price": 108.0,
                "global_start_index": 100,
                "global_end_index": 124,
                "choch_zone": {"lower_boundary": 92.0, "upper_boundary": 96.0},
            }
        if calls["n"] == 2:
            return {
                "leg_index": 1,
                "start_index": 5,
                "end_index": 20,
                "start_price": 98.0,
                "end_price": 110.0,
                "global_start_index": 105,
                "global_end_index": 120,
                "choch_zone": {"lower_boundary": 95.0, "upper_boundary": 99.0},
            }
        return None

    monkeypatch.setattr(walker_module, "find_crossing_attempt", _attempt)

    report = walk_structure(candles, result, _default_filter_config(), max_depth=4)
    assert report["total_mitigation_count"] == 2


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
        "total_mitigation_count",
        "max_depth_reached",
        "deepest_termination_reason",
        "active_level",
        "waiting_for",
        "stars_aligned",
    }
    for key in required_keys:
        assert key in report, f"Missing key: {key}"

    if report["levels"]:
        level_required_keys = {
            "depth",
            "slice_start",
            "slice_end",
            "rmt_result",
            "first_impulse",
            "first_impulse_global_start",
            "first_impulse_global_end",
            "internal_result",
            "structural_level",
            "choch_zone",
            "crossing_attempt",
            "choch_mitigated",
            "termination_reason",
            "child",
        }
        for key in level_required_keys:
            assert key in report["levels"][0], f"Missing level key: {key}"


def test_first_impulse_matches_selected_structural_level():
    candles, result = _make_downtrend_with_retracement()
    state = walk_structure(candles, result, _default_filter_config())
    if state["walkable"] and state["levels"]:
        level = state["levels"][0]
        if level.get("first_impulse"):
            assert level["first_impulse"]["start_index"] == level["slice_start"]
            assert level["first_impulse"]["end_index"] == level["first_impulse_global_end"]
            assert level["first_impulse"]["end_price"] == level["structural_level"]["price"]


def test_bos_equals_first_impulse_end_price():
    candles, result = _make_downtrend_with_retracement()
    state = walk_structure(candles, result, _default_filter_config())
    if state["walkable"] and state["levels"]:
        level = state["levels"][0]
        if level.get("first_impulse") and level.get("structural_level"):
            assert level["structural_level"]["price"] == level["first_impulse"]["end_price"]


# ---------------------------------------------------------------------------
# find_crossing_attempt
# ---------------------------------------------------------------------------


def test_find_crossing_attempt_returns_none_when_no_crossing():
    # Prices never reach BOS=100.0 after first_move_end=0; max high = 97*1.001 = 97.097
    prices = [90.0, 91.0, 92.0, 93.0, 94.0, 95.0, 94.0, 93.0, 94.0, 95.0, 96.0, 97.0]
    candles = _make_candles(prices)
    structural_level = {"price": 100.0}

    attempt = find_crossing_attempt(
        candles=candles,
        slice_start=0,
        slice_end=len(candles) - 1,
        first_move_end=0,
        structural_level=structural_level,
        choch_zone=None,
        global_trend="down",
    )
    assert attempt is None


def test_find_crossing_attempt_returns_first_crossing():
    # First move ends at index 4.  Post-first-move dips to index 6 (lowest low),
    # then rallies crossing BOS=95.0 at index 8, and continues higher to index 9
    # before the scan window ends — extreme_index = 9.
    prices = [90.0, 91.0, 92.0, 93.0, 93.0, 92.0, 91.0, 92.0, 96.0, 97.0]
    candles = _make_candles(prices)
    structural_level = {"price": 95.0}

    attempt = find_crossing_attempt(
        candles=candles,
        slice_start=0,
        slice_end=len(candles) - 1,
        first_move_end=4,
        structural_level=structural_level,
        choch_zone=None,
        global_trend="down",
    )
    assert attempt is not None
    # Extreme high is at index 9 (97 * 1.001 = 97.097) — last candle, loop exhausts
    assert attempt["global_end_index"] == 9
    # Lowest low between index 4 and first_crossing_index=8: index 6 (91 * 0.999)
    assert attempt["global_start_index"] == 6
    assert attempt["end_price"] == candles[9].high
    assert attempt["start_price"] == candles[6].low


# ---------------------------------------------------------------------------
# serialize_state_report
# ---------------------------------------------------------------------------


def test_serialize_state_report_is_json_serializable():
    """Serialized state report must be json.dumps compatible."""
    import json
    candles, result = _make_downtrend_with_retracement()
    state = walk_structure(candles, result, _default_filter_config())
    serialized = serialize_state_report(state)
    # Must not raise
    json_str = json.dumps(serialized)
    assert isinstance(json_str, str)
    assert len(json_str) > 10
    # first_move_candles must be stripped
    for level in serialized.get("levels", []):
        assert "first_move_candles" not in level
        assert "internal_result" not in level
        assert "rmt_result" not in level
