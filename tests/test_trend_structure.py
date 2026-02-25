"""Tests for src.core.trend_structure.detect_structure()."""
from __future__ import annotations

from datetime import datetime, timedelta

from src.core.features import Candle
from src.core.trend_structure import detect_structure


def make_candles(prices):
    """Create synthetic Candles: open=close=price, high=p+0.5, low=p-0.5."""
    return [
        Candle(
            timestamp=datetime(2024, 1, 1) + timedelta(hours=i),
            open=float(p),
            high=float(p) + 0.5,
            low=float(p) - 0.5,
            close=float(p),
        )
        for i, p in enumerate(prices)
    ]


# ---------------------------------------------------------------------------
# Test 1 — clear downtrend: multiple swing cycles, >=2 BOS events
# ---------------------------------------------------------------------------

def test_detect_structure_downtrend():
    """Clear downtrend: >=2 BOS events, decreasing BOS prices, alternating legs.

    Trace (high=p+0.5, low=p-0.5):
      Init [100..95]: trend='down', last_extreme=100.5
      i=5(94): impulse, last_extreme->93.5
      i=6(93): impulse, last_extreme->92.5
      i=7(94): high=94.5 > 92.5 -> impulse->retracement
      i=8(91): low=90.5 < 92.5  -> retracement->impulse, BOS(92.5)
      i=9(92): high=92.5 > 90.5 -> impulse->retracement
      i=10(89): low=88.5 < 90.5 -> retracement->impulse, BOS(90.5)
      => 2 BOS events: [92.5, 90.5] (decreasing)
    """
    prices = [100, 98, 96, 97, 95, 94, 93, 94, 91, 92, 89]
    candles = make_candles(prices)
    result = detect_structure(candles)

    assert result["trend"] == "down", f"Expected 'down', got '{result['trend']}'"

    assert len(result["bos_events"]) >= 2, (
        f"Expected >=2 BOS events, got {len(result['bos_events'])}"
    )

    # BOS prices must be strictly decreasing (each break is lower)
    bos_prices = [e["price"] for e in result["bos_events"]]
    for i in range(1, len(bos_prices)):
        assert bos_prices[i] < bos_prices[i - 1], (
            f"BOS prices not decreasing at position {i}: {bos_prices}"
        )

    # Legs must strictly alternate impulse/retracement
    types = [leg["type"] for leg in result["legs"]]
    assert len(types) >= 2, "Expected at least 2 legs in downtrend"
    for i in range(1, len(types)):
        assert types[i] != types[i - 1], (
            f"Non-alternating legs at index {i}: {types}"
        )


# ---------------------------------------------------------------------------
# Test 2 — clear uptrend: >=1 BOS event, increasing BOS prices
# ---------------------------------------------------------------------------

def test_detect_structure_uptrend():
    """Clear uptrend: >=1 BOS event, BOS prices increasing.

    Trace:
      Init [100..102]: trend='up', last_extreme=99.5
      i=5(107): impulse, last_extreme->107.5
      i=6(103): low=102.5 < 107.5 -> impulse->retracement
      i=7(110): high=110.5 > 107.5 -> retracement->impulse, BOS(107.5)
      => 1 BOS event: [107.5]
    """
    prices = [100, 103, 101, 105, 102, 107, 103, 110]
    candles = make_candles(prices)
    result = detect_structure(candles)

    assert result["trend"] == "up", f"Expected 'up', got '{result['trend']}'"

    assert len(result["bos_events"]) >= 1, (
        f"Expected >=1 BOS event, got {len(result['bos_events'])}"
    )

    # BOS prices must be increasing (each break is higher)
    bos_prices = [e["price"] for e in result["bos_events"]]
    for i in range(1, len(bos_prices)):
        assert bos_prices[i] > bos_prices[i - 1], (
            f"BOS prices not increasing at position {i}: {bos_prices}"
        )


# ---------------------------------------------------------------------------
# Test 3 — flat / range market
# ---------------------------------------------------------------------------

def test_detect_structure_range():
    """Flat oscillating market produces trend=='range' or zero BOS events."""
    # Init [100..101]: trend='up' (101>100), last_extreme=98.5
    # Walk: prices oscillate 99-101, no candle low dips below 98.5 in impulse,
    # no candle high exceeds last_extreme in retracement -> no BOS -> range
    prices = [100, 101, 99, 100, 101, 99, 100, 101, 99]
    candles = make_candles(prices)
    result = detect_structure(candles)

    assert result["trend"] == "range" or result["bos_events"] == [], (
        f"Expected range or no BOS events; got trend='{result['trend']}', "
        f"bos_events={result['bos_events']}"
    )


# ---------------------------------------------------------------------------
# Test 4 — first impulse leg has bos_level = None (no preceding BOS)
# ---------------------------------------------------------------------------

def test_detect_structure_first_impulse_no_bos():
    """The very first leg is always an impulse with bos_level=None."""
    prices = [100, 98, 96, 97, 95, 94, 93, 94, 91, 92, 89]
    candles = make_candles(prices)
    result = detect_structure(candles)

    assert len(result["legs"]) > 0, "Expected at least one leg"

    first_leg = result["legs"][0]
    assert first_leg["type"] == "impulse", (
        f"First leg must be 'impulse', got '{first_leg['type']}'"
    )
    assert first_leg["bos_level"] is None, (
        f"First impulse must have bos_level=None, got {first_leg['bos_level']}"
    )
