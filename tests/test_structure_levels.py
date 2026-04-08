from datetime import datetime, timedelta

from src.core.features import Candle
from src.core.structure_levels import (
    compute_all_structure_levels,
    compute_bos_levels,
    compute_choch_level,
    compute_internal_structure_levels,
    compute_last_impulse_internal_choch_zone,
)


def _make_candles(closes: list[float]) -> list[Candle]:
    base = datetime(2024, 1, 1)
    candles: list[Candle] = []
    for i, close in enumerate(closes):
        candles.append(
            Candle(
                timestamp=base + timedelta(hours=i),
                open=close,
                high=close,
                low=close,
                close=close,
                volume=100,
            )
        )
    return candles


def test_bos_count_matches_confirmed_impulses():
    candles = _make_candles([100, 95, 90, 92, 89, 91, 88, 90, 87, 86, 85])
    legs = [
        {"type": "impulse", "confirmed": True, "start_price": 100, "end_price": 90, "start_index": 0, "end_index": 2},
        {"type": "retracement", "confirmed": True, "start_price": 90, "end_price": 92, "start_index": 2, "end_index": 3},
        {"type": "impulse", "confirmed": True, "start_price": 92, "end_price": 89, "start_index": 3, "end_index": 4},
        {"type": "retracement", "confirmed": True, "start_price": 89, "end_price": 91, "start_index": 4, "end_index": 5},
        {"type": "impulse", "confirmed": True, "start_price": 91, "end_price": 88, "start_index": 5, "end_index": 6},
    ]

    bos_levels = compute_bos_levels(candles, legs)

    assert len(bos_levels) == 3


def test_bos_line_starts_at_impulse_end():
    candles = _make_candles([100, 95, 90, 92, 89, 91, 88, 90, 87, 86, 85])
    legs = [
        {"type": "impulse", "confirmed": True, "start_price": 100, "end_price": 90, "start_index": 0, "end_index": 2},
        {"type": "impulse", "confirmed": True, "start_price": 92, "end_price": 89, "start_index": 3, "end_index": 4},
        {"type": "impulse", "confirmed": True, "start_price": 91, "end_price": 88, "start_index": 5, "end_index": 6},
    ]

    bos_levels = compute_bos_levels(candles, legs)
    impulse_ends = [leg["end_index"] for leg in legs]

    assert [bos["start_index"] for bos in bos_levels] == impulse_ends


def test_bos_broken_when_price_crosses():
    candles = _make_candles([100, 96, 90, 89, 88, 91, 89])
    legs = [
        {
            "type": "impulse",
            "confirmed": True,
            "start_price": 100,
            "end_price": 90,
            "start_index": 0,
            "end_index": 2,
        }
    ]

    bos_levels = compute_bos_levels(candles, legs)

    assert len(bos_levels) == 1
    assert bos_levels[0]["broken"] is True
    assert bos_levels[0]["end_index"] == len(candles) - 1
    assert bos_levels[0]["break_index"] == 5


def test_bos_unbroken_when_price_never_crosses():
    candles = _make_candles([100, 96, 90, 89, 88, 87, 86])
    legs = [
        {
            "type": "impulse",
            "confirmed": True,
            "start_price": 100,
            "end_price": 90,
            "start_index": 0,
            "end_index": 2,
        }
    ]

    bos_levels = compute_bos_levels(candles, legs)

    assert len(bos_levels) == 1
    assert bos_levels[0]["broken"] is False
    assert bos_levels[0]["end_index"] == len(candles) - 1
    assert bos_levels[0]["break_index"] is None


def test_compute_last_impulse_internal_choch_zone():
    candles = _make_candles(list(range(100, 120)))
    internal_legs = [
        {
            "type": "impulse",
            "confirmed": True,
            "start_price": 100.0,
            "end_price": 105.0,
            "start_index": 0,
            "end_index": 2,
        },
        {
            "type": "impulse",
            "confirmed": True,
            "start_price": 104.0,
            "end_price": 110.0,
            "start_index": 2,
            "end_index": 5,
        },
    ]
    parent = {
        "type": "impulse",
        "confirmed": True,
        "start_price": 90.0,
        "end_price": 115.0,
        "start_index": 3,
        "end_index": 18,
        "internal_structure": {"trend": "up", "legs": internal_legs},
    }
    out = compute_last_impulse_internal_choch_zone(candles, [parent])
    assert out is not None
    assert out["lower_boundary"] == 104.0
    assert out["upper_boundary"] == 105.0
    assert out["source_impulse_start_index_global"] == 3 + 2


def test_choch_uses_most_recent_impulse_start():
    candles = _make_candles([100, 96, 90, 94, 89, 93, 88, 92])
    legs = [
        {"type": "impulse", "confirmed": True, "start_price": 100, "end_price": 90, "start_index": 0, "end_index": 2},
        {"type": "retracement", "confirmed": True, "start_price": 90, "end_price": 94, "start_index": 2, "end_index": 3},
        {"type": "impulse", "confirmed": True, "start_price": 94, "end_price": 89, "start_index": 3, "end_index": 4},
    ]

    choch = compute_choch_level(candles, legs, "down")

    assert choch is not None
    assert choch["price"] == 94
    assert choch["start_index"] == 3


def test_choch_none_when_no_confirmed_legs():
    candles = _make_candles([100, 99, 98, 97, 96])
    one_impulse_legs = [
        {
            "type": "impulse",
            "confirmed": True,
            "start_price": 100,
            "end_price": 98,
            "start_index": 0,
            "end_index": 2,
        }
    ]

    assert compute_choch_level(candles, [], "down") is None
    assert compute_choch_level(candles, one_impulse_legs, "down") is None


def test_choch_requires_two_impulses():
    candles = _make_candles([100, 96, 92, 95, 94, 93])
    legs = [
        {
            "type": "impulse",
            "confirmed": True,
            "start_price": 100,
            "end_price": 92,
            "start_index": 0,
            "end_index": 2,
        },
        {
            "type": "retracement",
            "confirmed": True,
            "start_price": 92,
            "end_price": 95,
            "start_index": 2,
            "end_index": 3,
        },
    ]

    assert compute_choch_level(candles, legs, "down") is None


def test_choch_broken_triggers_on_close():
    candles = _make_candles([100, 97, 90, 95, 89, 101, 99])
    legs = [
        {
            "type": "impulse",
            "confirmed": True,
            "start_price": 100,
            "end_price": 90,
            "start_index": 0,
            "end_index": 2,
        },
        {
            "type": "retracement",
            "confirmed": True,
            "start_price": 90,
            "end_price": 95,
            "start_index": 2,
            "end_index": 3,
        },
        {
            "type": "impulse",
            "confirmed": True,
            "start_price": 95,
            "end_price": 89,
            "start_index": 3,
            "end_index": 4,
        }
    ]

    choch = compute_choch_level(candles, legs, "down")

    assert choch is not None
    assert choch["broken"] is True
    assert choch["end_index"] == len(candles) - 1


def test_compute_all_structure_levels_combines_outputs():
    candles = _make_candles([100, 96, 90, 94, 89, 88, 87])
    legs = [
        {
            "type": "impulse",
            "confirmed": True,
            "start_price": 100,
            "end_price": 90,
            "start_index": 0,
            "end_index": 2,
        }
    ]

    payload = compute_all_structure_levels(candles, legs, "down")

    assert "bos_levels" in payload
    assert "choch_level" in payload
    assert len(payload["bos_levels"]) == 1
    assert payload["choch_level"] is None


def test_internal_choch_extends_to_full_chart_when_unbroken():
    candles = _make_candles([200 - i for i in range(50)])
    parent_leg = {
        "type": "impulse",
        "confirmed": True,
        "start_index": 10,
        "end_index": 30,
        "internal_structure": {
            "trend": "down",
            "legs": [
                {
                    "type": "impulse",
                    "confirmed": True,
                    "start_price": 190,
                    "end_price": 180,
                    "start_index": 0,
                    "end_index": 5,
                },
                {
                    "type": "retracement",
                    "confirmed": True,
                    "start_price": 180,
                    "end_price": 185,
                    "start_index": 5,
                    "end_index": 8,
                },
                {
                    "type": "impulse",
                    "confirmed": True,
                    "start_price": 185,
                    "end_price": 170,
                    "start_index": 8,
                    "end_index": 12,
                },
            ],
        },
    }

    compute_internal_structure_levels(candles, [parent_leg])

    assert parent_leg["internal_choch_level"] is not None
    assert parent_leg["internal_choch_level"]["end_index"] == len(candles) - 1


def test_internal_choch_extends_to_full_chart_when_broken():
    candles = _make_candles([200, 198, 196, 194, 192, 190, 188, 186, 184, 182, 180, 178, 176, 174, 172, 170, 168, 166, 164, 162, 160, 188, 158, 156, 154, 152, 150, 148, 146, 144, 142, 140, 138, 136, 134, 132, 130, 128, 126, 124, 122, 120, 118, 116, 114, 112, 110, 108, 106, 104])
    parent_leg = {
        "type": "impulse",
        "confirmed": True,
        "start_index": 10,
        "end_index": 30,
        "internal_structure": {
            "trend": "down",
            "legs": [
                {
                    "type": "impulse",
                    "confirmed": True,
                    "start_price": 190,
                    "end_price": 180,
                    "start_index": 0,
                    "end_index": 5,
                },
                {
                    "type": "retracement",
                    "confirmed": True,
                    "start_price": 180,
                    "end_price": 185,
                    "start_index": 5,
                    "end_index": 8,
                },
                {
                    "type": "impulse",
                    "confirmed": True,
                    "start_price": 185,
                    "end_price": 170,
                    "start_index": 8,
                    "end_index": 12,
                },
            ],
        },
    }

    compute_internal_structure_levels(candles, [parent_leg])

    assert parent_leg["internal_choch_level"] is not None
    assert parent_leg["internal_choch_level"]["broken"] is True
    assert parent_leg["internal_choch_level"]["end_index"] == len(candles) - 1


def test_internal_bos_start_index_offset_correctly():
    candles = _make_candles([200 - i for i in range(50)])
    parent_leg = {
        "type": "impulse",
        "confirmed": True,
        "start_index": 10,
        "end_index": 30,
        "internal_structure": {
            "trend": "down",
            "legs": [
                {
                    "type": "impulse",
                    "confirmed": True,
                    "start_price": 190,
                    "end_price": 182,
                    "start_index": 2,
                    "end_index": 8,
                }
            ],
        },
    }

    compute_internal_structure_levels(candles, [parent_leg])

    assert parent_leg["internal_bos_levels"][0]["start_index"] == 18
