"""Trend identification engine for Chronos-AI.
Pure, stateless function that classifies a candle window as uptrend / downtrend / range
and segments it into alternating impulse/retracement legs.
"""
from __future__ import annotations
from datetime import datetime
from typing import List, Dict, Any

def _collect_candidates(candles: List[Any], from_index: int, direction: str, min_swing_candles: int) -> List[Dict]:
    """Scan forward from from_index to find local min/max."""
    candidates = []
    # BUG FIX 2: Start scanning strictly AFTER from_index
    start_idx = from_index + 1
    
    for i in range(start_idx, len(candles) - min_swing_candles):
        if i < min_swing_candles:
            continue
            
        window = candles[i - min_swing_candles : i + min_swing_candles + 1]
        
        if direction == "low":
            if candles[i].low == min(c.low for c in window):
                candidates.append({"price": candles[i].low, "index": i, "timestamp": candles[i].timestamp})
        elif direction == "high":
            if candles[i].high == max(c.high for c in window):
                candidates.append({"price": candles[i].high, "index": i, "timestamp": candles[i].timestamp})
                
    return candidates

def _score_candidates(candles: List[Any], candidates: List[Dict], direction: str) -> List[Dict]:
    """Score candidates based on retracement size looking forward."""
    scored = []
    for cand in candidates:
        i = cand["index"]
        c_price = cand["price"]
        
        # BUG FIX 2: Only scan forward from the candidate
        forward_candles = candles[i + 1:]
        
        if direction == "low":
            # Find next lower low
            next_idx = len(candles) - 1
            for j, c in enumerate(forward_candles):
                if c.low < c_price:
                    next_idx = i + 1 + j
                    break
            
            # Retracement peak between candidate and next lower low
            sub_window = candles[i : next_idx + 1]
            retracement_peak = max(c.high for c in sub_window) if sub_window else c_price
            score = retracement_peak - c_price
            
        else: # direction == "high"
            # Find next higher high
            next_idx = len(candles) - 1
            for j, c in enumerate(forward_candles):
                if c.high > c_price:
                    next_idx = i + 1 + j
                    break
                    
            # Retracement trough between candidate and next higher high
            sub_window = candles[i : next_idx + 1]
            retracement_trough = min(c.low for c in sub_window) if sub_window else c_price
            score = c_price - retracement_trough
            
        cand["score"] = score
        scored.append(cand)
        
    return scored

def identify_trend(candles: List[Any], min_swing_candles: int = 3, trend_confirmation_pct: float = 0.03) -> Dict:
    if len(candles) < 10:
        return {"trend": "range", "trend_start": None, "legs": [], "current_phase": "unknown"}

    # STEP 1: CLASSIFY WINDOW
    highest_price = max(c.high for c in candles)
    lowest_price = min(c.low for c in candles)
    
    peak_index = next(i for i, c in enumerate(candles) if c.high == highest_price)
    trough_index = next(i for i, c in enumerate(candles) if c.low == lowest_price)

    total_range = highest_price - lowest_price
    
    # BUG FIX 1: Calculate relative percentage move instead of absolute
    pct_move = total_range / highest_price if highest_price > 0 else 0
    if pct_move < trend_confirmation_pct:
        return {"trend": "range", "trend_start": None, "legs": [], "current_phase": "unknown"}

    if peak_index < trough_index:
        trend = "down"
        trend_start = {"price": highest_price, "index": peak_index, "timestamp": candles[peak_index].timestamp}
    else:
        trend = "up"
        trend_start = {"price": lowest_price, "index": trough_index, "timestamp": candles[trough_index].timestamp}

    # STEP 5: BUILD LEGS ITERATIVELY
    legs = []
    current_start = trend_start
    phase_is_impulse = True

    while True:
        direction = "low" if (trend == "down" and phase_is_impulse) or (trend == "up" and not phase_is_impulse) else "high"
        
        candidates = _collect_candidates(candles, current_start["index"], direction, min_swing_candles)
        if not candidates:
            # Add open leg and stop
            legs.append({
                "type": "impulse" if phase_is_impulse else "retracement",
                "start_price": current_start["price"],
                "start_index": current_start["index"],
                "start_timestamp": current_start["timestamp"],
                "end_price": None,
                "end_index": None,
                "end_timestamp": None,
                "confirmed": False,
                "slope": None
            })
            break

        scored = _score_candidates(candles, candidates, direction)
        best = max(scored, key=lambda c: c["score"])

        slope = (best["price"] - current_start["price"]) / (best["index"] - current_start["index"])
        
        legs.append({
            "type": "impulse" if phase_is_impulse else "retracement",
            "start_price": current_start["price"],
            "start_index": current_start["index"],
            "start_timestamp": current_start["timestamp"],
            "end_price": best["price"],
            "end_index": best["index"],
            "end_timestamp": best["timestamp"],
            "confirmed": True,
            "slope": slope
        })

        current_start = best
        phase_is_impulse = not phase_is_impulse

        if best["index"] >= len(candles) - min_swing_candles:
            break

    current_phase = "unknown"
    if legs:
        current_phase = legs[-1]["type"]

    return {
        "trend": trend,
        "trend_start": trend_start,
        "legs": legs,
        "current_phase": current_phase
    }