"""Tests for src/core/trend_id.py — identify_trend()."""
from datetime import datetime, timedelta
from src.core.features import Candle, compute_ema
from src.core.trend_id import filter_crossovers_in_impulses, identify_trend

def _make_candles(prices: list) -> list:
    """Build minimal Candle list from a sequence of close/high/low prices."""
    base = datetime(2024, 1, 1)
    return [
        Candle(
            timestamp=base + timedelta(hours=i),
            open=p, high=p, low=p, close=p, volume=100
        ) for i, p in enumerate(prices)
    ]


# Oscillating series where ANCHOR-TO-NOW (most recent significant extreme) still yields
# multiple confirmed impulses — used for momentum / dominance filter tests.
_MULTI_IMPULSE_PRICES_FOR_FILTERS = [
    987, 960, 999, 972, 1002, 999, 966, 984, 960, 988, 1045, 1047, 1012, 967, 924, 973, 922, 919, 881,
    936, 967, 963, 914, 957, 984, 1032, 1012, 1037, 1021, 1051, 999, 1009, 1018, 995, 1049, 1027, 1075,
    1035, 1066, 1096, 1154, 1183, 1204, 1166, 1207, 1193,
]


def test_clear_downtrend():
    prices = [100, 98, 99, 96, 97, 93, 95, 90, 92, 88, 89, 85]
    # min_swing_candles=1 required because dataset is so small
    result = identify_trend(_make_candles(prices), min_swing_candles=1)

    assert result["trend"] == "down"
    assert result["trend_start"] is not None
    assert result["trend_start"]["price"] > prices[-1]
    assert result["legs"][0]["type"] == "impulse"


def test_clear_uptrend():
    prices = [80, 82, 81, 85, 83, 88, 86, 92, 90, 95]
    result = identify_trend(_make_candles(prices), min_swing_candles=1)

    assert result["trend"] == "up"
    assert result["trend_start"] is not None
    assert result["trend_start"]["price"] < prices[-1]
    assert result["legs"][0]["type"] == "impulse"

def test_flat_range():
    prices = [100, 101, 99, 100, 101, 99, 100, 101, 99, 100]
    result = identify_trend(_make_candles(prices), min_swing_candles=1)
    
    assert result["trend"] == "range"


def _confirmed_impulses(result: dict) -> list:
    return [
        leg
        for leg in result["legs"]
        if leg["type"] == "impulse" and leg["confirmed"] and leg["end_price"] is not None
    ]


def _impulse_distance(leg: dict) -> float:
    return abs(leg["end_price"] - leg["start_price"])


def test_parent_relative_filter_rejects_small_impulse():
    prices = [1000, 1010, 1005, 1012, 1008, 1015, 1010, 1016, 1011, 1017, 2000]
    result = identify_trend(
        _make_candles(prices),
        min_swing_candles=1,
        use_parent_relative_filter=True,
        min_impulse_parent_ratio=0.15,
    )

    threshold = (max(prices) - min(prices)) * 0.15
    assert all(_impulse_distance(leg) >= threshold for leg in _confirmed_impulses(result))


def test_momentum_filter_rejects_decaying_impulse():
    prices = _MULTI_IMPULSE_PRICES_FOR_FILTERS
    base = identify_trend(_make_candles(prices), min_swing_candles=1)
    filtered = identify_trend(
        _make_candles(prices),
        min_swing_candles=1,
        use_momentum_filter=True,
        min_momentum_ratio=0.5,
    )

    base_impulses = _confirmed_impulses(base)
    filtered_impulses = _confirmed_impulses(filtered)
    assert len(base_impulses) >= 2
    assert len(filtered_impulses) == 1


def test_dominance_filter_rejects_weak_impulse():
    prices = _MULTI_IMPULSE_PRICES_FOR_FILTERS
    result = identify_trend(
        _make_candles(prices),
        min_swing_candles=1,
        use_dominance_filter=True,
        min_dominance_ratio=1.2,
    )

    assert len(result["legs"]) >= 3
    assert result["legs"][1]["type"] == "retracement"
    assert result["legs"][1]["confirmed"] is True
    assert result["legs"][2]["type"] == "impulse"
    assert result["legs"][2]["confirmed"] is False


def test_all_filters_disabled_preserves_original_behaviour():
    prices = [80, 82, 81, 85, 83, 88, 86, 92, 90, 95]
    baseline = identify_trend(_make_candles(prices), min_swing_candles=1)
    explicit_defaults = identify_trend(
        _make_candles(prices),
        min_swing_candles=1,
        use_parent_relative_filter=False,
        min_impulse_parent_ratio=0.15,
        use_momentum_filter=False,
        min_momentum_ratio=0.3,
        use_dominance_filter=False,
        min_dominance_ratio=1.2,
    )

    assert explicit_defaults == baseline


def test_filters_are_independent():
    prices = _MULTI_IMPULSE_PRICES_FOR_FILTERS
    baseline = identify_trend(_make_candles(prices), min_swing_candles=1)
    momentum_only = identify_trend(
        _make_candles(prices),
        min_swing_candles=1,
        use_parent_relative_filter=False,
        min_impulse_parent_ratio=0.15,
        use_momentum_filter=True,
        min_momentum_ratio=0.5,
        use_dominance_filter=False,
        min_dominance_ratio=1.2,
    )

    baseline_impulses = _confirmed_impulses(baseline)
    momentum_impulses = _confirmed_impulses(momentum_only)

    assert len(baseline_impulses) >= 2
    assert len(momentum_impulses) == 1
    assert _impulse_distance(momentum_impulses[0]) == _impulse_distance(baseline_impulses[0])


def test_ema_crossover_in_impulse_only():
    candles = _make_candles([100] * 21 + [110] * 5 + [90] * 5 + [110] * 5)
    ema9 = compute_ema(candles, 9)
    ema21 = compute_ema(candles, 21)

    crossover_indices = []
    for index in range(1, len(candles)):
        previous_ema9 = ema9[index - 1]
        previous_ema21 = ema21[index - 1]
        current_ema9 = ema9[index]
        current_ema21 = ema21[index]
        if (
            previous_ema9 is None
            or previous_ema21 is None
            or current_ema9 is None
            or current_ema21 is None
        ):
            continue
        previous_diff = previous_ema9 - previous_ema21
        current_diff = current_ema9 - current_ema21
        previous_sign = 1 if previous_diff > 0 else -1 if previous_diff < 0 else 0
        current_sign = 1 if current_diff > 0 else -1 if current_diff < 0 else 0
        if previous_sign != current_sign:
            crossover_indices.append(index)

    assert crossover_indices == [21, 27, 32]

    legs = [
        {
            "type": "impulse",
            "confirmed": True,
            "start_index": 20,
            "end_index": 24,
        },
        {
            "type": "retracement",
            "confirmed": True,
            "start_index": 25,
            "end_index": 30,
        },
    ]

    filtered_indices = filter_crossovers_in_impulses(crossover_indices, legs)

    assert filtered_indices == [21]
    assert 27 not in filtered_indices
    assert 32 not in filtered_indices


def test_crossover_suppressed_in_internal_retracement():
    legs = [
        {
            "type": "impulse",
            "confirmed": True,
            "start_index": 0,
            "end_index": 20,
            "internal_structure": {
                "legs": [
                    {"type": "impulse", "confirmed": True, "start_index": 0, "end_index": 4},
                    {"type": "retracement", "confirmed": True, "start_index": 5, "end_index": 10},
                    {"type": "impulse", "confirmed": True, "start_index": 11, "end_index": 15},
                ]
            },
        }
    ]

    assert filter_crossovers_in_impulses([7], legs, suppress_indices={7}) == []
    assert filter_crossovers_in_impulses([7], legs, suppress_indices=set()) == [7]