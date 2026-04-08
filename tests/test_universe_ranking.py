"""Tests for universe ranking job."""

from __future__ import annotations

from src.scanner import universe_ranking as ur


def test_get_ranking_status_has_expected_keys():
    s = ur.get_ranking_status()
    for k in (
        "in_progress",
        "total_symbols",
        "symbols_scored",
        "current_symbol",
        "started_at",
        "completed_at",
        "last_error",
        "estimated_seconds_remaining",
        "global_structure_in_progress",
        "prime_impulse_in_progress",
        "walker_in_progress",
    ):
        assert k in s


def test_compute_ranking_metrics_under_three_confirmed_legs_zero_total():
    result = {
        "legs": [
            {"type": "impulse", "confirmed": True, "start_price": 1, "end_price": 2, "start_index": 0, "end_index": 5},
            {"type": "retracement", "confirmed": True, "start_price": 2, "end_price": 1.5, "start_index": 5, "end_index": 8},
        ],
        "current_phase": "retracement",
    }
    ipr, ivr, *_rest, total = ur.compute_ranking_metrics(result)
    assert total == 0.0
    assert ipr == 0.0


def test_compute_ranking_metrics_formula():
    result = {
        "legs": [
            {"type": "impulse", "confirmed": True, "start_price": 100.0, "end_price": 110.0, "start_index": 0, "end_index": 2},
            {"type": "retracement", "confirmed": True, "start_price": 110.0, "end_price": 105.0, "start_index": 2, "end_index": 4},
            {"type": "impulse", "confirmed": True, "start_price": 105.0, "end_price": 115.0, "start_index": 4, "end_index": 6},
        ],
        "current_phase": "impulse",
    }
    ipr, ivr, pc, vc, base, total = ur.compute_ranking_metrics(result)
    assert ipr > 0
    assert ivr > 0
    assert base == (pc * 0.7) + (vc * 0.3)
    assert total <= 100.0


def test_choose_basis_prefers_more_legs_when_both_qualify():
    res_w = {"legs": [{"confirmed": True}, {"confirmed": True}, {"confirmed": True}]}
    res_d = {"legs": [{"confirmed": True}, {"confirmed": True}, {"confirmed": True}, {"confirmed": True}]}
    tf, res, force = ur._choose_basis_and_result(res_w, res_d)
    assert tf == "1d"
    assert res is res_d
    assert force is False


def test_trigger_ranking_async_refuses_when_in_progress():
    with ur._ranking_lock:
        ur._ranking_status["in_progress"] = True
    try:
        out = ur.trigger_ranking_async()
        assert out == {"started": False, "reason": "already_running"}
    finally:
        with ur._ranking_lock:
            ur._ranking_status["in_progress"] = False
