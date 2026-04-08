"""Unit tests for CHoCH candidate pivot band and reference BOS."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from src.core.choch_candidate_move import (
    find_candidate_pivot_index,
    pivot_high_price_allowed,
    pivot_low_price_allowed,
    reference_bos_before_pivot,
    structure_broken_from_close,
    union_zone_bounds,
)


@dataclass
class _C:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


def _ts(minute: int) -> datetime:
    return datetime(2025, 1, 1, 12, minute, tzinfo=timezone.utc)


def test_union_zone_bounds():
    g = {"lower_boundary": 100.0, "upper_boundary": 110.0}
    i = {"lower_boundary": 105.0, "upper_boundary": 115.0}
    assert union_zone_bounds(g, i) == (100.0, 115.0)
    assert union_zone_bounds(g, None) == (100.0, 110.0)
    assert union_zone_bounds(None, None) is None


def test_pivot_low_allowed_inside_and_below_zone():
    z_lo, z_hi = 100.0, 110.0
    floor = 95.0
    assert pivot_low_price_allowed(105.0, z_lo, z_hi, floor) is True
    assert pivot_low_price_allowed(98.0, z_lo, z_hi, floor) is True
    assert pivot_low_price_allowed(94.0, z_lo, z_hi, floor) is False
    assert pivot_low_price_allowed(111.0, z_lo, z_hi, floor) is False


def test_pivot_high_allowed_inside_and_above_zone():
    z_lo, z_hi = 100.0, 110.0
    ceiling = 120.0
    assert pivot_high_price_allowed(105.0, z_lo, z_hi, ceiling) is True
    assert pivot_high_price_allowed(115.0, z_lo, z_hi, ceiling) is True
    assert pivot_high_price_allowed(121.0, z_lo, z_hi, ceiling) is False
    assert pivot_high_price_allowed(99.0, z_lo, z_hi, ceiling) is False


def test_find_candidate_pivot_uptrend_deepest_low_tiebreak_latest():
    # min_swing=1: window [i-1,i,i+1], local min at low
    candles = [
        _C(_ts(0), 100, 101, 99, 100),
        _C(_ts(1), 100, 102, 98, 101),  # swing low 98 at i=1
        _C(_ts(2), 101, 103, 100, 102),
        _C(_ts(3), 102, 104, 101, 103),
        _C(_ts(4), 103, 105, 102, 104),  # swing low 102 at i=4 — higher than 98
        _C(_ts(5), 104, 106, 103, 105),
    ]
    gz = {"lower_boundary": 97.0, "upper_boundary": 103.0}
    iz = {"lower_boundary": 97.0, "upper_boundary": 103.0}
    last_impulse = {"start_index": 0, "start_price": 97.0}
    idx = find_candidate_pivot_index(
        candles, "up", gz, iz, last_impulse, min_swing_candles=1
    )
    assert idx == 1


def test_find_candidate_pivot_uptrend_two_equal_lows_pick_later():
    candles = [
        _C(_ts(0), 100, 101, 99.5, 100),
        _C(_ts(1), 100, 102, 99.0, 101),
        _C(_ts(2), 101, 103, 100, 102),
        _C(_ts(3), 102, 104, 99.0, 103),  # same min 99.0, later index
        _C(_ts(4), 103, 105, 102, 104),
    ]
    gz = {"lower_boundary": 98.0, "upper_boundary": 104.0}
    last_impulse = {"start_index": 0, "start_price": 98.0}
    idx = find_candidate_pivot_index(
        candles, "up", gz, None, last_impulse, min_swing_candles=1
    )
    assert idx == 3


def test_reference_bos_before_pivot_and_structure_broken():
    legs = [
        {
            "type": "impulse",
            "confirmed": True,
            "start_index": 0,
            "end_index": 2,
            "end_price": 50.0,
        },
        {
            "type": "retracement",
            "confirmed": True,
            "start_index": 2,
            "end_index": 4,
            "end_price": 48.0,
        },
        {
            "type": "impulse",
            "confirmed": True,
            "start_index": 4,
            "end_index": 6,
            "end_price": 55.0,
        },
    ]
    ref = reference_bos_before_pivot(legs, pivot_index=5)
    assert ref is not None
    price, end_i = ref
    assert end_i == 2
    assert price == 50.0

    assert structure_broken_from_close("up", 51.0, 50.0) is True
    assert structure_broken_from_close("up", 49.0, 50.0) is False
    assert structure_broken_from_close("down", 49.0, 50.0) is True
    assert structure_broken_from_close("down", 51.0, 50.0) is False


def test_reference_bos_none_when_no_prior_impulse():
    legs = [
        {
            "type": "impulse",
            "confirmed": True,
            "start_index": 0,
            "end_index": 10,
            "end_price": 50.0,
        },
    ]
    assert reference_bos_before_pivot(legs, pivot_index=3) is None
