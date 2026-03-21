"""
Tests for PIP-based trend identification (trend_id_pip.py).
"""

from datetime import datetime, timedelta
from src.core.features import Candle
from src.core.trend_id_pip import (
    extract_pips,
    classify_pip_legs,
    compute_pip_internal_structure,
    identify_trend_pip,
)
from src.core.trend_id import identify_trend


def _make_candles(prices: list) -> list:
    """Create a list of Candles from prices (all OHLC = price)."""
    base = datetime(2024, 1, 1)
    return [
        Candle(
            timestamp=base + timedelta(hours=i),
            open=p,
            high=p,
            low=p,
            close=p,
            volume=100,
        )
        for i, p in enumerate(prices)
    ]


def test_extract_pips_returns_endpoints():
    """First and last PIPs always have index 0 and len(candles)-1."""
    candles = _make_candles([100, 102, 101, 103, 102, 104, 103, 105])
    pips = extract_pips(candles, n_pips=5, dist_measure="perpendicular")

    assert len(pips) > 0
    assert pips[0]["index"] == 0
    assert pips[-1]["index"] == len(candles) - 1


def test_extract_pips_count():
    """Returned PIP count does not exceed n_pips."""
    candles = _make_candles([100, 102, 101, 103, 102, 104, 103, 105, 102, 106])
    pips = extract_pips(candles, n_pips=7, dist_measure="perpendicular")

    assert len(pips) <= 7
    # Should be close to requested, unless candle list is very short
    assert len(pips) >= 2


def test_extract_pips_sorted_by_index():
    """PIPs are strictly sorted by index (ascending)."""
    candles = _make_candles([100, 110, 95, 120, 90, 125, 85, 130])
    pips = extract_pips(candles, n_pips=6, dist_measure="perpendicular")

    indices = [pip["index"] for pip in pips]
    assert indices == sorted(indices)
    # Also check strictly ascending (no duplicates)
    assert len(indices) == len(set(indices))


def test_all_three_dist_measures_run():
    """All three distance measures execute without exception."""
    candles = _make_candles([100, 105, 102, 110, 98, 115, 95, 120])

    for measure in ["vertical", "perpendicular", "euclidean"]:
        pips = extract_pips(candles, n_pips=5, dist_measure=measure)
        assert len(pips) > 0
        assert len(pips) <= 5


def test_clear_downtrend_classified_correctly():
    """Descending prices classify as downtrend with correct impulse direction."""
    # Clear downtrend with small bounces
    candles = _make_candles([200, 190, 195, 180, 185, 170, 175, 160, 165, 150])
    result = identify_trend_pip(candles, n_pips=7, dist_measure="perpendicular")

    assert result["trend"] == "down"
    # All impulse legs should be down (negative slope)
    for leg in result["legs"]:
        if leg["type"] == "impulse":
            assert leg["end_price"] <= leg["start_price"], f"Impulse leg should go down, got {leg}"


def test_clear_uptrend_classified_correctly():
    """Ascending prices classify as uptrend with correct impulse direction."""
    # Clear uptrend with small pullbacks
    candles = _make_candles([100, 110, 105, 120, 115, 130, 125, 140, 135, 150])
    result = identify_trend_pip(candles, n_pips=7, dist_measure="perpendicular")

    assert result["trend"] == "up"
    # All impulse legs should be up (positive slope)
    for leg in result["legs"]:
        if leg["type"] == "impulse":
            assert leg["end_price"] >= leg["start_price"], f"Impulse leg should go up, got {leg}"


def test_internal_structure_contained():
    """Internal leg indices are within parent impulse boundaries."""
    candles = _make_candles([100, 110, 105, 120, 115, 130, 125, 140, 135, 150, 140, 160])
    result = identify_trend_pip(candles, n_pips=9, dist_measure="perpendicular")

    for leg in result["legs"]:
        if leg["internal_structure"] is not None:
            parent_start = leg["start_index"]
            parent_end = leg["end_index"]
            parent_length = parent_end - parent_start

            for internal_leg in leg["internal_structure"]["legs"]:
                # Internal indices are relative to the slice [0, parent_length]
                assert 0 <= internal_leg["start_index"] <= parent_length
                assert internal_leg["end_index"] is None or 0 <= internal_leg["end_index"] <= parent_length


def test_output_schema_matches_identify_trend():
    """Output schema matches identify_trend() keys and leg structure."""
    candles = _make_candles([100, 110, 105, 120, 115, 130, 125, 140])
    pip_result = identify_trend_pip(candles, n_pips=7, dist_measure="perpendicular")
    original_result = identify_trend(candles, min_swing_candles=1)

    # Top-level keys must match
    assert set(pip_result.keys()) == set(original_result.keys())
    assert set(pip_result.keys()) == {"trend", "trend_start", "legs", "current_phase"}

    # Each leg must have required keys
    for leg in pip_result["legs"]:
        assert "type" in leg
        assert "start_index" in leg
        assert "end_index" in leg
        assert "confirmed" in leg
        assert "start_price" in leg
        assert "end_price" in leg
        assert "start_timestamp" in leg
        assert "end_timestamp" in leg
        assert "slope" in leg


def test_range_detection():
    """Flat oscillating sequence classifies as range."""
    # Roughly equal up and down moves
    candles = _make_candles([100, 110, 100, 110, 100, 110, 100, 110, 100])
    result = identify_trend_pip(candles, n_pips=7, dist_measure="perpendicular")

    assert result["trend"] == "range"


def test_early_stop_on_short_candles():
    """Short candle lists don't cause crashes; return gracefully with <= n_pips."""
    candles = _make_candles([100, 110, 105])
    pips = extract_pips(candles, n_pips=20, dist_measure="perpendicular")

    assert len(pips) <= min(20, len(candles))
    assert len(pips) >= 2  # At least endpoints


def test_all_confirmed_in_pip_output():
    """All legs from classify_pip_legs have confirmed=True."""
    candles = _make_candles([100, 110, 105, 120, 115, 130])
    pips = extract_pips(candles, n_pips=6, dist_measure="perpendicular")
    result = classify_pip_legs(pips)

    for leg in result["legs"]:
        assert leg["confirmed"] is True


def test_slope_calculation():
    """Slope is correctly calculated as (end_price - start_price) / (end_index - start_index)."""
    candles = _make_candles([100, 120, 110])
    pips = extract_pips(candles, n_pips=3, dist_measure="perpendicular")
    result = classify_pip_legs(pips)

    # Should have 2 legs: 0->1 (up slope=20), 1->2 (down slope=-10)
    assert len(result["legs"]) == 2

    leg0_slope = result["legs"][0]["slope"]
    leg1_slope = result["legs"][1]["slope"]

    assert leg0_slope > 0  # First leg up
    assert leg1_slope < 0  # Second leg down
