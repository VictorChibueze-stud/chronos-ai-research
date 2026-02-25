"""Trend structure detection: impulse/retracement phase segmentation.

Identifies the macro trend by segmenting price action into alternating
impulse and retracement legs using a Break-Of-Structure (BOS) state machine.

The algorithm is purely deterministic (no indicators, no lookback parameters):
  - A retracement lasts until price exceeds the last impulse extreme.
  - When it does, the retracement ends, the impulse resumes, and a BOS is emitted.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.core.features import Candle


def detect_structure(candles: List[Candle]) -> Dict[str, Any]:
    """Segment candles into impulse/retracement legs and detect BOS events.

    Setup (first 5 candles):
      - trend = "down" if candles[4].close < candles[0].close
      - trend = "up"   if candles[4].close > candles[0].close
      - trend = "range"/unknown otherwise (early return)
      - last_extreme = highest high (downtrend) or lowest low (uptrend)
        of the first 5 candles.
      - Phase starts as "impulse"; first leg opens at index 0.

    Walk (index 5 onwards):
      Downtrend --
        impulse:      if high > last_extreme -> end impulse, start retracement
                      else                  -> last_extreme = min(last_extreme, low)
        retracement:  if low < last_extreme  -> end retrace, start impulse,
                                               emit BOS(price=last_extreme),
                                               last_extreme = low
      Uptrend (mirror) --
        impulse:      if low < last_extreme  -> end impulse, start retracement
                      else                  -> last_extreme = max(last_extreme, high)
        retracement:  if high > last_extreme -> end retrace, start impulse,
                                               emit BOS(price=last_extreme),
                                               last_extreme = high

    Range detection:
      If no BOS events were emitted after the full walk, trend is set to "range".

    The last leg is always left open (end_index=None, end_price=None).

    Args:
        candles: Chronological list of Candle objects.

    Returns:
        {
          "trend"        : "up" | "down" | "range",
          "legs"         : List[Dict] with keys:
                             type, start_index, end_index,
                             start_price, end_price, bos_level
          "bos_events"   : List[Dict] with keys: price, index, timestamp
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

    if len(candles) < 5:
        return _empty

    # ------------------------------------------------------------------
    # 1. Determine initial direction and last_extreme from first 5 candles
    # ------------------------------------------------------------------
    first_close: float = candles[0].close
    last_close:  float = candles[4].close

    last_extreme: float
    trend: str

    if last_close < first_close:
        trend = "down"
        last_extreme = max(c.high for c in candles[:5])
    elif last_close > first_close:
        trend = "up"
        last_extreme = min(c.low for c in candles[:5])
    else:
        # Equal closes -> indeterminate -> return range immediately
        return _empty

    # ------------------------------------------------------------------
    # 2. State
    # ------------------------------------------------------------------
    current_phase = "impulse"
    legs: List[Dict[str, Any]] = []
    bos_events: List[Dict[str, Any]] = []

    def _open_leg(
        phase: str,
        idx: int,
        price: float,
        bos_lvl: Optional[float],
    ) -> None:
        legs.append({
            "type": phase,
            "start_index": idx,
            "end_index": None,
            "start_price": float(price),
            "end_price": None,
            "bos_level": float(bos_lvl) if bos_lvl is not None else None,
        })

    def _close_leg(idx: int, price: float) -> None:
        if legs:
            legs[-1]["end_index"] = idx
            legs[-1]["end_price"] = float(price)

    # Open first leg (impulse, no preceding BOS)
    _open_leg("impulse", 0, candles[0].close, None)

    # ------------------------------------------------------------------
    # 3. Walk forward from index 5
    # ------------------------------------------------------------------
    for i in range(5, len(candles)):
        c = candles[i]

        if trend == "down":
            if current_phase == "retracement":
                if c.low < last_extreme:
                    # Retracement ends: impulse resumes, BOS emitted
                    _close_leg(i, c.low)
                    _open_leg("impulse", i, c.low, last_extreme)
                    bos_events.append({
                        "price": float(last_extreme),
                        "index": i,
                        "timestamp": c.timestamp,
                    })
                    last_extreme = c.low
                    current_phase = "impulse"
                # else: still retracing (track for context; no state change)

            else:  # impulse
                if c.high > last_extreme:
                    # Impulse interrupted: retracement begins
                    _close_leg(i, c.high)
                    _open_leg("retracement", i, c.high, None)
                    current_phase = "retracement"
                else:
                    # Impulse continues: extend extreme lower
                    last_extreme = min(last_extreme, c.low)

        else:  # trend == "up"
            if current_phase == "retracement":
                if c.high > last_extreme:
                    # Retracement ends: impulse resumes, BOS emitted
                    _close_leg(i, c.high)
                    _open_leg("impulse", i, c.high, last_extreme)
                    bos_events.append({
                        "price": float(last_extreme),
                        "index": i,
                        "timestamp": c.timestamp,
                    })
                    last_extreme = c.high
                    current_phase = "impulse"

            else:  # impulse
                if c.low < last_extreme:
                    # Impulse interrupted: retracement begins
                    _close_leg(i, c.low)
                    _open_leg("retracement", i, c.low, None)
                    current_phase = "retracement"
                else:
                    # Impulse continues: extend extreme higher
                    last_extreme = max(last_extreme, c.high)

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
