"""Trend structure detection: impulse/retracement phase segmentation.

Identifies the macro trend by segmenting swing-point sequences into alternating
impulse and retracement legs using a Break-Of-Structure (BOS) state machine.

The algorithm operates on swing points (output of detect_swings()), not raw
candles. Each transition between swing-point types drives phase changes:
  - In a downtrend, an SH mid-impulse signals a counter-move (retracement
    begins); an SL that breaks the last extreme during retracement confirms a
    BOS and resumes the impulse.
  - Uptrend is the exact mirror.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.core.features import Candle, detect_swings


def detect_structure(swings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Segment swing points into impulse/retracement legs and detect BOS events.

    Args:
        swings: Output of detect_swings() — a list of dicts with keys:
                  type ("SH"|"SL"), price (float), index (int),
                  timestamp (datetime|None), strength (float).

    Setup (first 2 points determine trend):
        SH → SL  →  trend = "down",  last_extreme = first SL price
        SL → SH  →  trend = "up",    last_extreme = first SH price
        At least 3 swing points required; otherwise returns "range" sentinel.

    Walk (index 1 onward):
        Downtrend / impulse:
            SH encountered  → counter-move; open retracement leg
            SL encountered  → new lower low; update last_extreme
        Downtrend / retracement:
            SL < last_extreme → BOS; close retrace, open new impulse
            SH               → still retracing; no state change
        Uptrend is the exact mirror (SL ↔ SH, < ↔ >).

    Range detection:
        If no BOS events are emitted, trend is overridden to "range".

    Returns:
        {
          "trend"        : "up" | "down" | "range",
          "legs"         : List[Dict] — type, start_index, end_index,
                           start_price, end_price, bos_level.
                           Indices are candle indices (swing["index"]).
          "bos_events"   : List[Dict] — price, index, timestamp.
          "current_phase": "impulse" | "retracement" | "unknown"
          "last_extreme" : float | None
        }
    """
    _empty: Dict[str, Any] = {
        "trend": "range",
        "legs": [],
        "bos_events": [],
        "current_phase": "unknown",
        "last_extreme": None,
    }

    if len(swings) < 3:
        return _empty

    # ------------------------------------------------------------------
    # 1. Determine initial direction from first 2 swing points
    # ------------------------------------------------------------------
    first, second = swings[0], swings[1]

    last_extreme: float
    trend: str

    if first["type"] == "SH" and second["type"] == "SL":
        trend = "down"
        last_extreme = float(second["price"])   # first SL price
    elif first["type"] == "SL" and second["type"] == "SH":
        trend = "up"
        last_extreme = float(second["price"])   # first SH price
    else:
        # Same-type consecutive opening swings: indeterminate
        return _empty

    # ------------------------------------------------------------------
    # 2. State machine helpers
    # ------------------------------------------------------------------
    current_phase = "impulse"
    legs: List[Dict[str, Any]] = []
    bos_events: List[Dict[str, Any]] = []

    def _open_leg(
        phase: str,
        candle_idx: int,
        price: float,
        bos_lvl: Optional[float],
    ) -> None:
        legs.append({
            "type": phase,
            "start_index": candle_idx,
            "end_index": None,
            "start_price": float(price),
            "end_price": None,
            "bos_level": float(bos_lvl) if bos_lvl is not None else None,
        })

    def _close_leg(candle_idx: int, price: float) -> None:
        if legs:
            legs[-1]["end_index"] = candle_idx
            legs[-1]["end_price"] = float(price)

    # Open the first leg (impulse; no preceding BOS)
    _open_leg("impulse", first["index"], float(first["price"]), None)

    # ------------------------------------------------------------------
    # 3. Walk swing points from index 1 onward
    # ------------------------------------------------------------------
    for pt in swings[1:]:
        pt_type  = pt["type"]
        pt_price = float(pt["price"])
        pt_idx   = int(pt["index"])
        pt_ts    = pt.get("timestamp")

        if trend == "down":
            if current_phase == "impulse":
                if pt_type == "SH":
                    # Counter-move: end impulse, begin retracement
                    _close_leg(pt_idx, pt_price)
                    _open_leg("retracement", pt_idx, pt_price, None)
                    current_phase = "retracement"
                else:
                    # SL: new lower low — extend the impulse extreme
                    last_extreme = pt_price

            else:  # retracement
                if pt_type == "SL" and pt_price < last_extreme:
                    # Retracement ends: BOS confirmed, impulse resumes
                    _close_leg(pt_idx, pt_price)
                    _open_leg("impulse", pt_idx, pt_price, last_extreme)
                    bos_events.append({
                        "price": float(last_extreme),
                        "index": pt_idx,
                        "timestamp": pt_ts,
                    })
                    last_extreme = pt_price
                    current_phase = "impulse"
                # else SH: still retracing; no state change

        else:  # trend == "up"
            if current_phase == "impulse":
                if pt_type == "SL":
                    # Counter-move: end impulse, begin retracement
                    _close_leg(pt_idx, pt_price)
                    _open_leg("retracement", pt_idx, pt_price, None)
                    current_phase = "retracement"
                else:
                    # SH: new higher high — extend the impulse extreme
                    last_extreme = pt_price

            else:  # retracement
                if pt_type == "SH" and pt_price > last_extreme:
                    # Retracement ends: BOS confirmed, impulse resumes
                    _close_leg(pt_idx, pt_price)
                    _open_leg("impulse", pt_idx, pt_price, last_extreme)
                    bos_events.append({
                        "price": float(last_extreme),
                        "index": pt_idx,
                        "timestamp": pt_ts,
                    })
                    last_extreme = pt_price
                    current_phase = "impulse"
                # else SL: still retracing; no state change

    # ------------------------------------------------------------------
    # 4. Range detection: no structural breaks found
    # ------------------------------------------------------------------
    if not bos_events:
        trend = "range"

    return {
        "trend": trend,
        "legs": legs,
        "bos_events": bos_events,
        "current_phase": current_phase,
        "last_extreme": float(last_extreme),
    }


def detect_structure_from_candles(
    candles: List[Candle],
    lookback: int = 15,
) -> Dict[str, Any]:
    """Convenience wrapper: detect_swings() → detect_structure().

    Args:
        candles:  Chronological list of Candle objects.
        lookback: Swing-detection lookback window (bars each side).

    Returns:
        Same dict as detect_structure().
    """
    highs  = [c.high for c in candles]
    lows   = [c.low  for c in candles]
    
    #swings = detect_swings(highs, lows, lookback=lookback, candles=candles)
    swings = detect_swings_atr(candles, atr_mult=atr_mult)
    
    return detect_structure(swings)
