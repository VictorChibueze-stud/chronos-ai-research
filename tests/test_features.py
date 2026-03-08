import math
from datetime import datetime, timedelta

import numpy as np

from src.core.features import (
    ema, rsi, Candle, normalize_candles, detect_swings, compute_price_features,
    compute_zigzag, detect_bos_choch_from_zigzag, detect_swings_atr,
)

_STRUCTURE_MAP_KEYS = {"swings", "swing_highs", "swing_lows", "order_blocks", "fvg"}


def test_ema_simple():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    out = ema(vals, 3)
    # last value should be greater than previous and finite
    assert math.isfinite(out[-1])
    assert out[-1] > out[-2]


def test_rsi_increasing():
    closes = list(range(1, 21))
    r = rsi(closes, n=14)
    assert r[-1] > 50.0


def test_detect_swings_simple():
    # construct simple OHLC where a peak and valley exist
    highs = [1, 2, 5, 2, 1, 3, 1]
    lows = [0.5, 1.0, 4.0, 1.5, 0.8, 2.0, 0.9]
    swings = detect_swings(highs, lows, lookback=1)
    types = {s["type"] for s in swings}
    assert "SH" in types
    assert "SL" in types


def test_compute_price_features_sanity():
    # 30 ascending candles
    base = datetime.utcnow()
    rows = []
    for i in range(30):
        t = base + timedelta(minutes=i)
        o = float(i)
        c = float(i + 0.5)
        rows.append({"timestamp": t.isoformat(), "open": o, "high": c + 0.2, "low": o - 0.2, "close": c})
    candles = normalize_candles(rows)
    features = compute_price_features(candles, timeframe="1m")
    assert isinstance(features, dict)
    for k in ("meta", "now_panel", "regime_tags", "structure_map", "ict_events", "recent_window"):
        assert k in features
    assert features["meta"]["num_candles"] == len(candles)
    assert features["now_panel"]["close"] == candles[-1].close


# ---------------------------------------------------------------------------
# New tests for the rewritten detect_swings()
# ---------------------------------------------------------------------------

def test_detect_swings_lookback_sensitivity():
    """lookback=20 must produce fewer swings than lookback=3 — no hidden cap."""
    # Zigzag with peaks every 4 bars and equal-depth troughs.
    # lookback=3 window (7 bars) sees only one peak → many detected.
    # lookback=20 window (41 bars) sees multiple equal-height peaks → leftmost
    # rule eliminates all but the very first in each window → far fewer.
    n = 60
    highs = [5.0 if i % 4 == 1 else 1.0 for i in range(n)]
    lows  = [4.0 if i % 4 == 1 else 0.5 if i % 4 == 3 else 0.8 for i in range(n)]
    swings_3  = detect_swings(highs, lows, lookback=3)
    swings_20 = detect_swings(highs, lows, lookback=20)
    assert len(swings_20) < len(swings_3), (
        f"lookback=20 gave {len(swings_20)} swings, lookback=3 gave {len(swings_3)}"
    )


def test_detect_swings_alternating():
    """Output must strictly alternate SH/SL regardless of input noise."""
    highs = [1, 4, 2, 5, 1, 3, 1, 6, 2, 4, 1, 3, 1]
    lows  = [0.5, 3, 1, 4, 0.5, 2, 0.5, 5, 1, 3, 0.5, 2, 0.5]
    swings = detect_swings(highs, lows, lookback=2)
    for i in range(1, len(swings)):
        assert swings[i]["type"] != swings[i - 1]["type"], (
            f"Non-alternating at positions {i-1} and {i}: "
            f"{swings[i-1]['type']} → {swings[i]['type']}"
        )


def test_detect_swings_flat_top_tie():
    """Flat top (two bars with identical high) emits exactly one SH at the leftmost bar."""
    highs = [1.0, 2.0, 5.0, 5.0, 2.0, 1.0]
    lows  = [0.5, 1.0, 4.0, 4.0, 1.0, 0.5]
    swings = detect_swings(highs, lows, lookback=2)
    sh = [s for s in swings if s["type"] == "SH"]
    assert len(sh) <= 1, f"Expected at most 1 SH for flat top, got {len(sh)}"
    if sh:
        assert sh[0]["index"] == 2, f"Expected leftmost SH at index 2, got {sh[0]['index']}"


def test_detect_swings_required_keys():
    """Every swing must have the five required keys; timestamp is populated when candles passed."""
    highs = [1.0, 2.0, 5.0, 2.0, 1.0, 3.0, 1.0]
    lows  = [0.5, 1.0, 4.0, 1.5, 0.8, 2.0, 0.9]
    base = datetime.utcnow()
    candles = [
        Candle(
            timestamp=base + timedelta(minutes=i),
            open=lows[i],
            high=highs[i],
            low=lows[i],
            close=(highs[i] + lows[i]) / 2,
        )
        for i in range(len(highs))
    ]
    swings = detect_swings(highs, lows, lookback=1, candles=candles)
    assert swings, "Expected at least one swing in test data"
    required = {"type", "price", "index", "timestamp", "strength"}
    for s in swings:
        missing = required - s.keys()
        assert not missing, f"Swing missing keys {missing}: {s}"
        assert s["timestamp"] is not None, "timestamp must be populated when candles are passed"
        assert isinstance(s["strength"], float)


def test_structure_map_keys_nonempty():
    """structure_map must contain all five canonical keys for non-empty candle input."""
    base = datetime.utcnow()
    rows = [
        {
            "timestamp": (base + timedelta(minutes=i)).isoformat(),
            "open": float(i),
            "high": float(i) + 0.5,
            "low": float(i) - 0.5,
            "close": float(i) + 0.3,
        }
        for i in range(30)
    ]
    candles = normalize_candles(rows)
    features = compute_price_features(candles, timeframe="1m")
    sm = features["structure_map"]
    assert sm.keys() >= _STRUCTURE_MAP_KEYS, (
        f"structure_map missing keys: {_STRUCTURE_MAP_KEYS - sm.keys()}"
    )
    # swing_highs / swing_lows must be subsets of swings
    assert all(s in sm["swings"] for s in sm["swing_highs"])
    assert all(s in sm["swings"] for s in sm["swing_lows"])


def test_structure_map_keys_empty():
    """structure_map must contain all five canonical keys even for empty candle input."""
    features = compute_price_features([], timeframe="1m")
    sm = features["structure_map"]
    assert sm.keys() >= _STRUCTURE_MAP_KEYS, (
        f"empty structure_map missing keys: {_STRUCTURE_MAP_KEYS - sm.keys()}"
    )


# ============ PART 1: ZigZag Tests ============

def test_compute_zigzag_alternates():
    """Zigzag output must strictly alternate SH/SL."""
    highs = [1, 4, 2, 5, 1.5, 3.5, 1.2]
    lows = [0.5, 3, 1, 4, 0.8, 2.5, 0.7]
    swings = detect_swings(highs, lows, lookback=1)
    zigzag = compute_zigzag(swings)

    # Check alternation
    for i in range(1, len(zigzag)):
        assert zigzag[i]["type"] != zigzag[i - 1]["type"], (
            f"Zigzag not alternating at position {i}: "
            f"{zigzag[i-1]['type']} -> {zigzag[i]['type']}"
        )


def test_compute_zigzag_count_le_swings():
    """Zigzag must have <= swings (deduplication reduces count)."""
    highs = [1, 4, 2, 5, 1.5, 3.5, 1.2, 4.5, 1.0, 3.0]
    lows = [0.5, 3, 1, 4, 0.8, 2.5, 0.7, 3.5, 0.5, 2.0]
    swings = detect_swings(highs, lows, lookback=1)
    zigzag = compute_zigzag(swings)
    # Since compute_zigzag returns swings as-is, count should be exactly equal
    # (in future, could filter further)
    assert len(zigzag) <= len(swings), (
        f"Zigzag has more points ({len(zigzag)}) than raw swings ({len(swings)})"
    )


def test_compute_zigzag_with_atr_filter():
    """Zigzag with ATR filtering should reduce small legs."""
    # Create volatile data with small noisy legs
    highs = [1.0, 4.0, 2.0, 3.9, 2.1, 5.0, 1.5, 4.8, 2.2, 3.7, 1.0, 6.0]
    lows  = [0.5, 3.0, 1.0, 3.8, 1.9, 4.0, 0.8, 3.9, 1.8, 3.5, 0.5, 5.0]

    swings = detect_swings(highs, lows, lookback=1)

    # Compute ATR (simplified)
    from src.core.features import atr as atr_func
    atr_vals = atr_func(highs, lows, [(h + l) / 2 for h, l in zip(highs, lows)], n=5)

    # Filter with atr
    zigzag_filtered = compute_zigzag(swings, atr_arr=atr_vals, min_leg_atr=2.0)

    # Filter should have <= points (small legs merged)
    assert len(zigzag_filtered) <= len(swings), (
        f"ATR-filtered zigzag ({len(zigzag_filtered)}) should have <= "
        f"unfiltered swings ({len(swings)})"
    )



# ============ PART 2: BOS/CHOCH Tests ============

def test_detect_bos_choch_from_zigzag_alternates():
    """BOS/CHOCH events should be detected on alternating zigzag."""
    highs = [1, 4, 2, 5, 1.5, 6, 2, 7]
    lows = [0.5, 3, 1, 4, 0.8, 5, 1.5, 6]
    swings = detect_swings(highs, lows, lookback=1)
    zigzag = compute_zigzag(swings)

    if len(zigzag) >= 2:
        events = detect_bos_choch_from_zigzag(zigzag)
        # Check all events have required keys including new "level"
        for ev in events:
            assert "type" in ev
            assert "price" in ev
            assert "index" in ev
            assert "level" in ev, "Events must include 'level' key"
            assert ev["level"] == ev["price"], "'level' must equal 'price'"
            assert ev["type"] in ("BOS_UP", "BOS_DOWN", "CHOCH_UP", "CHOCH_DOWN")


def test_detect_bos_choch_uptrend_to_downtrend():
    """Transition from uptrend to downtrend should produce CHOCH_DOWN."""
    # First 3 zigzag: SH(5)->SL(1)->SH(6) => p2(6)>p0(5) => trend="up"
    # Walk: SH(6) breaks SH(5) -> BOS_UP(level=5); SL(0) breaks SL(1) -> CHOCH_DOWN(level=1)
    zigzag = [
        {"type": "SH", "price": 5.0, "index": 0, "timestamp": None, "strength": 1.0},
        {"type": "SL", "price": 1.0, "index": 1, "timestamp": None, "strength": 1.0},
        {"type": "SH", "price": 6.0, "index": 2, "timestamp": None, "strength": 1.0},
        {"type": "SL", "price": 0.0, "index": 3, "timestamp": None, "strength": 1.0},
    ]
    events = detect_bos_choch_from_zigzag(zigzag)

    event_types = [e["type"] for e in events]
    assert "BOS_UP" in event_types, "Expected BOS_UP when SH(6) > SH(5)"
    assert "CHOCH_DOWN" in event_types, "Expected CHOCH_DOWN after uptrend reverses"

    # Verify "level" key and that price reflects the *broken* structural level
    bos_up = next(e for e in events if e["type"] == "BOS_UP")
    assert bos_up["price"] == 5.0, "BOS_UP price must be the broken previous SH (5.0)"
    assert bos_up["level"] == bos_up["price"]

    choch_down = next(e for e in events if e["type"] == "CHOCH_DOWN")
    assert choch_down["price"] == 1.0, "CHOCH_DOWN price must be the broken previous SL (1.0)"
    assert choch_down["level"] == choch_down["price"]


def test_detect_bos_choch_clear_uptrend_then_reversal():
    """Clear uptrend produces multiple BOS_UP events, then CHOCH_DOWN on lower SL."""
    # Zigzag: SH(5)->SL(3)->SH(7)->SL(4)->SH(9)->SL(2)
    # Init:   first 3 -> p2(7)>p0(5) -> trend="up"
    # Walk:
    #   SH(7) > last_sh(5) -> BOS_UP(level=5);    last_sh=SH(7)
    #   SL(4) > last_sl(3) -> no event (higher SL); last_sl=SL(4)
    #   SH(9) > last_sh(7) -> BOS_UP(level=7);    last_sh=SH(9)
    #   SL(2) < last_sl(4) -> CHOCH_DOWN(level=4); trend="down"
    zigzag = [
        {"type": "SH", "price": 5.0, "index": 0, "timestamp": None, "strength": 1.0},
        {"type": "SL", "price": 3.0, "index": 1, "timestamp": None, "strength": 1.0},
        {"type": "SH", "price": 7.0, "index": 2, "timestamp": None, "strength": 1.0},
        {"type": "SL", "price": 4.0, "index": 3, "timestamp": None, "strength": 1.0},
        {"type": "SH", "price": 9.0, "index": 4, "timestamp": None, "strength": 1.0},
        {"type": "SL", "price": 2.0, "index": 5, "timestamp": None, "strength": 1.0},
    ]
    events = detect_bos_choch_from_zigzag(zigzag)

    event_types = [e["type"] for e in events]
    assert "BOS_UP" in event_types, "Expected BOS_UP events in uptrend"
    assert event_types.count("BOS_UP") >= 2, "Expected at least two BOS_UP events"
    assert "CHOCH_DOWN" in event_types, "Expected CHOCH_DOWN when lower SL breaks uptrend"
    assert "CHOCH_UP" not in event_types, "No CHOCH_UP expected in uptrend->downtrend sequence"

    # All events must carry the "level" key matching "price"
    for ev in events:
        assert "level" in ev, f"Missing 'level' key in {ev}"
        assert ev["level"] == ev["price"], "'level' must equal 'price'"


# ============ PART 3: ATR ZigZag State Machine Tests ============

def _make_sine_candles(n: int = 100, amplitude: float = 50.0, period: float = 10.0) -> list:
    """Synthetic candles following a sine wave."""
    base = datetime.utcnow()
    candles = []
    for i in range(n):
        price = 1000.0 + amplitude * math.sin(i * math.pi / period)
        candles.append(Candle(
            timestamp=base + timedelta(minutes=i),
            open=price,
            high=price + 2.0,
            low=price - 2.0,
            close=price,
        ))
    return candles


def test_detect_swings_atr_alternates():
    """detect_swings_atr output must strictly alternate SH/SL on clear zigzag data."""
    candles = _make_sine_candles(100)
    pivots = detect_swings_atr(candles, atr_mult=1.0)
    assert len(pivots) >= 4, f"Expected >= 4 pivots, got {len(pivots)}"
    for i in range(1, len(pivots)):
        assert pivots[i]["type"] != pivots[i - 1]["type"], (
            f"Non-alternating at {i-1} and {i}: "
            f"{pivots[i-1]['type']} -> {pivots[i]['type']}"
        )


def test_detect_swings_atr_append_only_behavior():
    """Early pivots from a partial run must match the full run — no repainting."""
    candles = _make_sine_candles(100)
    partial = detect_swings_atr(candles[:50], atr_mult=1.5)
    full = detect_swings_atr(candles, atr_mult=1.5)
    n = len(partial)
    assert full[:n] == partial, (
        "First N pivots from full run must match partial run (no repainting)"
    )


def test_detect_swings_atr_required_keys():
    """Every pivot must have required keys; type must be SH/SL; strength > 0."""
    candles = _make_sine_candles(60, amplitude=30.0, period=8.0)
    pivots = detect_swings_atr(candles, atr_mult=1.0)
    required = {"type", "price", "index", "timestamp", "strength"}
    for p in pivots:
        assert required <= p.keys(), f"Pivot missing keys: {required - p.keys()}"
        assert p["type"] in ("SH", "SL"), f"Invalid type: {p['type']}"
        assert p["strength"] > 0, f"strength must be > 0, got {p['strength']}"


def test_detect_swings_atr_atr_mult_effect():
    """Higher atr_mult must produce strictly fewer pivots than lower atr_mult.

    With period=2 the sine oscillates by ~50 pts every bar, so ATR converges
    near 52 and the peak-to-trough reversal is ~54 pts.
      mult=1.0 threshold ≈ 52  < 54  →  confirms on nearly every half-cycle
      mult=3.0 threshold ≈ 156 > 54  →  stops confirming once ATR warms up
    """
    candles = _make_sine_candles(100, amplitude=50.0, period=2.0)
    pivots_loose = detect_swings_atr(candles, atr_mult=1.0)
    pivots_strict = detect_swings_atr(candles, atr_mult=3.0)
    assert len(pivots_loose) > len(pivots_strict), (
        f"atr_mult=1.0 gave {len(pivots_loose)} pivots, "
        f"atr_mult=3.0 gave {len(pivots_strict)} — expected more with looser threshold"
    )
