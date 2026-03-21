"""Tests for src.core.trend_structure.detect_structure()."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Tuple

from src.core.trend_structure import detect_structure, detect_structure_from_candles


def make_swings(sequence: List[Tuple[str, float]]):
    """Build synthetic swing points from (type, price) pairs.

    Each entry gets a candle index equal to its position in the list, and a
    timestamp offset by that many hours from 2024-01-01.
    """
    return [
        {
            "type": t,
            "price": float(p),
            "index": i,
            "timestamp": datetime(2024, 1, 1) + timedelta(hours=i),
            "strength": 1.0,
        }
        for i, (t, p) in enumerate(sequence)
    ]


# ---------------------------------------------------------------------------
# Test 1 — clear downtrend swings: 2 BOS events at [90, 85]
# ---------------------------------------------------------------------------

def test_detect_structure_downtrend():
    """Clear downtrend: 2 BOS events at [90.0, 85.0], alternating legs.

    Swing trace:
      SH@100 → SL@90  : setup → trend='down', last_extreme=90
      SL@90           : walk[1] impulse SL  → last_extreme stays 90
      SH@95           : walk[2] impulse SH  → retracement opens
      SL@85 < 90      : walk[3] retrace SL  → BOS(90), impulse opens, last_extreme=85
      SH@88           : walk[4] impulse SH  → retracement opens
      SL@78 < 85      : walk[5] retrace SL  → BOS(85), impulse opens, last_extreme=78
    """
    swings = make_swings([
        ("SH", 100), ("SL", 90), ("SH", 95), ("SL", 85), ("SH", 88), ("SL", 78),
    ])
    result = detect_structure(swings)

    assert result["trend"] == "down", f"Expected 'down', got '{result['trend']}'"

    bos_prices = [e["price"] for e in result["bos_events"]]
    assert bos_prices == [90.0, 85.0], f"Expected [90.0, 85.0], got {bos_prices}"

    types = [leg["type"] for leg in result["legs"]]
    assert len(types) >= 2, "Expected at least 2 legs"
    for i in range(1, len(types)):
        assert types[i] != types[i - 1], f"Non-alternating legs at index {i}: {types}"


# ---------------------------------------------------------------------------
# Test 2 — clear uptrend swings: 2 BOS events at [110, 115]
# ---------------------------------------------------------------------------

def test_detect_structure_uptrend():
    """Clear uptrend: 2 BOS events at [110.0, 115.0], alternating legs.

    Swing trace:
      SL@100 → SH@110 : setup → trend='up', last_extreme=110
      SH@110          : walk[1] impulse SH  → last_extreme stays 110
      SL@105          : walk[2] impulse SL  → retracement opens
      SH@115 > 110    : walk[3] retrace SH  → BOS(110), impulse opens, last_extreme=115
      SL@108          : walk[4] impulse SL  → retracement opens
      SH@120 > 115    : walk[5] retrace SH  → BOS(115), impulse opens, last_extreme=120
    """
    swings = make_swings([
        ("SL", 100), ("SH", 110), ("SL", 105), ("SH", 115), ("SL", 108), ("SH", 120),
    ])
    result = detect_structure(swings)

    assert result["trend"] == "up", f"Expected 'up', got '{result['trend']}'"

    bos_prices = [e["price"] for e in result["bos_events"]]
    assert bos_prices == [110.0, 115.0], f"Expected [110.0, 115.0], got {bos_prices}"

    types = [leg["type"] for leg in result["legs"]]
    for i in range(1, len(types)):
        assert types[i] != types[i - 1], f"Non-alternating legs at index {i}: {types}"


# ---------------------------------------------------------------------------
# Test 3 — only 2 swings (not enough to start)
# ---------------------------------------------------------------------------

def test_detect_structure_too_few_swings():
    """Only 2 swings: must return gracefully without raising."""
    swings = make_swings([("SH", 100), ("SL", 90)])
    result = detect_structure(swings)

    # Must not crash; state is indeterminate
    assert result["trend"] == "range" or result["legs"] == [], (
        f"Expected range or empty legs; got trend='{result['trend']}', legs={result['legs']}"
    )


# ---------------------------------------------------------------------------
# Test 4 — first impulse leg has bos_level = None (no preceding BOS)
# ---------------------------------------------------------------------------

def test_detect_structure_first_impulse_no_bos():
    """The very first leg must always be an impulse with bos_level=None."""
    swings = make_swings([
        ("SH", 100), ("SL", 90), ("SH", 95), ("SL", 85), ("SH", 88), ("SL", 78),
    ])
    result = detect_structure(swings)

    assert len(result["legs"]) > 0, "Expected at least one leg"
    first_leg = result["legs"][0]
    assert first_leg["type"] == "impulse", (
        f"First leg must be 'impulse', got '{first_leg['type']}'"
    )
    assert first_leg["bos_level"] is None, (
        f"First impulse must have bos_level=None, got {first_leg['bos_level']}"
    )
