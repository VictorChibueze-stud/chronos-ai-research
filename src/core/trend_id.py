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

def identify_trend(
    candles: List[Any],
    min_swing_candles: int = 3,
    trend_confirmation_pct: float = 0.03,
    # Filter 1: Rejects impulses smaller than X% of the full window's price range. Increase ratio to demand larger impulses relative to the chart window. Useful for suppressing noise in internal structure detection.
    use_parent_relative_filter: bool = False,
    min_impulse_parent_ratio: float = 0.15,
    # Filter 2: Rejects impulses smaller than X% of the previous confirmed impulse. Prevents momentum decay from being misread as continuation. Increase ratio to demand stronger, more consistent impulse sizes throughout the trend.
    use_momentum_filter: bool = False,
    min_momentum_ratio: float = 0.3,
    # Filter 3: Rejects impulses that are smaller than X times the retracement that preceded them. Ensures the impulse demonstrates real directional dominance over the counter-move. A ratio of 1.2 means the impulse must be 20% larger than the retracement.
    use_dominance_filter: bool = False,
    min_dominance_ratio: float = 1.2,
) -> Dict:
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

        scored = sorted(
            _score_candidates(candles, candidates, direction),
            key=lambda c: c["score"],
            reverse=True,
        )

        best = None

        if not phase_is_impulse:
            # Retracement endpoint: pick extreme price, not highest score
            # Down trend retracement goes up - pick highest price reached
            # Up trend retracement goes down - pick lowest price reached
            if trend == "down":
                best = max(scored, key=lambda c: c["price"])
            else:
                best = min(scored, key=lambda c: c["price"])

        else:
            # Impulse endpoint: score-based selection with filters
            for candidate in scored:
                candidate_distance = abs(candidate["price"] - current_start["price"])
                rejected = False

                if use_parent_relative_filter:
                    min_parent_distance = min_impulse_parent_ratio * total_range
                    if candidate_distance < min_parent_distance:
                        rejected = True

                if not rejected and use_momentum_filter:
                    previous_impulse = next(
                        (
                            leg
                            for leg in reversed(legs)
                            if leg["type"] == "impulse"
                            and leg["confirmed"]
                            and leg["end_price"] is not None
                        ),
                        None,
                    )
                    if previous_impulse is not None:
                        previous_impulse_distance = abs(
                            previous_impulse["end_price"] - previous_impulse["start_price"]
                        )
                        if candidate_distance < (min_momentum_ratio * previous_impulse_distance):
                            rejected = True

                if not rejected and use_dominance_filter and legs:
                    previous_leg = legs[-1]
                    if (
                        previous_leg["type"] == "retracement"
                        and previous_leg["confirmed"]
                        and previous_leg["end_price"] is not None
                    ):
                        previous_retracement_distance = abs(
                            previous_leg["end_price"] - previous_leg["start_price"]
                        )
                        if candidate_distance < (min_dominance_ratio * previous_retracement_distance):
                            rejected = True

                if not rejected:
                    best = candidate
                    break

        if best is None:
            legs.append({
                "type": "impulse" if phase_is_impulse else "retracement",
                "start_price": current_start["price"],
                "start_index": current_start["index"],
                "start_timestamp": current_start["timestamp"],
                "end_price": None,
                "end_index": None,
                "end_timestamp": None,
                "confirmed": False,
                "slope": None,
            })
            break

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
    confirmed_legs = [l for l in legs if l.get("confirmed") is True]
    if confirmed_legs:
        current_phase = confirmed_legs[-1]["type"]
    elif legs:
        # Edge case: only unconfirmed legs exist (e.g. range with single open leg)
        current_phase = legs[-1]["type"]

    return {
        "trend": trend,
        "trend_start": trend_start,
        "legs": legs,
        "current_phase": current_phase
    }


def compute_internal_structure(
    candles: List[Any],
    legs: List[Dict],
    min_swing_candles: int = 3,
    trend_confirmation_pct: float = 0.005,
    use_parent_relative_filter: bool = False,
    min_impulse_parent_ratio: float = 0.15,
    use_momentum_filter: bool = False,
    min_momentum_ratio: float = 0.3,
    use_dominance_filter: bool = False,
    min_dominance_ratio: float = 1.2,
) -> List[Dict]:
    """For each confirmed impulse leg, run identify_trend on the leg's candle slice
    and store the result as leg['internal_structure'].  Non-impulse, unconfirmed, or
    too-short slices get internal_structure = None.  Mutates legs in place and returns it.

    trend_confirmation_pct defaults to 0.005 (0.5%) — much smaller than the outer
    identify_trend default of 3%, because impulse sub-slices are short by definition.
    """
    for leg in legs:
        if leg["type"] != "impulse" or not leg["confirmed"] or leg["end_index"] is None:
            leg["internal_structure"] = None
            continue

        start_index = leg["start_index"]
        end_index = leg["end_index"]
        slice_candles = candles[start_index : end_index + 1]

        if len(slice_candles) < 10:
            leg["internal_structure"] = None
            continue

        result = identify_trend(
            slice_candles,
            min_swing_candles=min_swing_candles,
            trend_confirmation_pct=trend_confirmation_pct,
            use_parent_relative_filter=use_parent_relative_filter,
            min_impulse_parent_ratio=min_impulse_parent_ratio,
            use_momentum_filter=use_momentum_filter,
            min_momentum_ratio=min_momentum_ratio,
            use_dominance_filter=use_dominance_filter,
            min_dominance_ratio=min_dominance_ratio,
        )
        leg["internal_structure"] = None if result["trend"] == "range" else result

    return legs


def filter_crossovers_in_impulses(
    crossover_indices: List[int],
    legs: List[Dict[str, Any]],
    suppress_indices: set[int] | None = None,
) -> List[int]:
    """Return crossover indices that fall inside confirmed impulse legs.

    When suppress_indices is provided, any crossover in that set is
    suppressed even if it is inside a confirmed impulse.
    """
    suppressed_indices = suppress_indices or set()
    filtered: List[int] = []
    for index in crossover_indices:
        if index in suppressed_indices:
            continue
        if any(
            leg.get("type") == "impulse"
            and leg.get("confirmed") is True
            and leg.get("start_index") is not None
            and leg.get("end_index") is not None
            and leg["start_index"] <= index <= leg["end_index"]
            for leg in legs
        ):
            filtered.append(index)
    return filtered