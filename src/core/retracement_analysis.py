"""Retracement Mini-Trend (RMT) analysis for Chronos-AI.

Pure stateless module. No side effects. No file I/O.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.core.choch_zone import compute_choch_proximity, get_active_choch_zone
from src.core.trend_id import identify_trend


# Finds the structural level of the Retracement Mini-Trend (RMT).
# In a global downtrend, the retracement goes UP, so the structural level
# is the highest high reached by any confirmed impulse leg in the RMT.
# In a global uptrend, the retracement goes DOWN, so the structural level
# is the lowest low reached by any confirmed impulse leg in the RMT.
# Returns None if the RMT has no confirmed impulse legs.
def find_rmt_structural_level(
    rmt_result: Dict[str, Any],
    global_trend: str,
) -> Optional[Dict[str, Any]]:
    """Find the structural level of the Retracement Mini-Trend.

    Args:
        rmt_result: Result dict from identify_trend run on the retracement slice.
        global_trend: Trend direction of the parent context — "up" or "down".

    Returns:
        Dict with price, source_leg_index, source_leg_end_index or None.
    """
    indexed_impulses = [
        (i, leg)
        for i, leg in enumerate(rmt_result["legs"])
        if (
            leg.get("type") == "impulse"
            and leg.get("confirmed") is True
            and leg.get("end_price") is not None
        )
    ]

    if not indexed_impulses:
        return None

    if global_trend == "down":
        # Retracement is upward — structural level is the highest end_price
        source_idx, source_leg = max(
            indexed_impulses, key=lambda x: float(x[1]["end_price"])
        )
    else:
        # global_trend == "up" — retracement is downward — structural level is lowest end_price
        source_idx, source_leg = min(
            indexed_impulses, key=lambda x: float(x[1]["end_price"])
        )

    return {
        "price": float(source_leg["end_price"]),
        "source_leg_index": source_idx,
        "source_leg_end_index": int(source_leg["end_index"]),
    }


# Finds all Attempts within the RMT — confirmed impulse legs whose
# end_price reached or crossed the RMT structural level.
# An Attempt is only a confirmed impulse leg — unconfirmed legs are excluded.
# Returns a list sorted by leg position (earliest first).
# Each Attempt dict includes the leg data plus attempt metadata.
def find_attempts(
    rmt_result: Dict[str, Any],
    structural_level: Dict[str, Any],
    global_trend: str,
) -> List[Dict[str, Any]]:
    """Find all Attempts within the RMT.

    Args:
        rmt_result: Result dict from identify_trend run on the retracement slice.
        structural_level: Dict from find_rmt_structural_level.
        global_trend: Trend direction of the parent context — "up" or "down".

    Returns:
        List of attempt dicts sorted by leg position (earliest first).
    """
    level_price = structural_level["price"]
    legs = rmt_result["legs"]
    attempts: List[Dict[str, Any]] = []

    for idx, leg in enumerate(legs):
        if leg.get("type") != "impulse" or leg.get("confirmed") is not True:
            continue
        if leg.get("end_price") is None:
            continue

        end_price = float(leg["end_price"])

        if global_trend == "down":
            reached = end_price >= level_price
        else:
            reached = end_price <= level_price

        if not reached:
            continue

        # Find the next confirmed retracement leg after this impulse
        next_retracement = None
        for j in range(idx + 1, len(legs)):
            cand = legs[j]
            if (
                cand.get("type") == "retracement"
                and cand.get("confirmed") is True
                and cand.get("end_price") is not None
            ):
                next_retracement = cand
                break

        if next_retracement is None:
            attempt_result = "pending"
        else:
            next_end = float(next_retracement["end_price"])
            if global_trend == "down":
                attempt_result = "false_break" if next_end < level_price else "real_break"
            else:
                attempt_result = "false_break" if next_end > level_price else "real_break"

        attempts.append(
            {
                "leg_index": idx,
                "start_index": int(leg["start_index"]),
                "end_index": int(leg["end_index"]),
                "start_price": float(leg["start_price"]),
                "end_price": end_price,
                "attempt_result": attempt_result,
            }
        )

    return attempts


def _build_result(
    retracement_leg: Dict[str, Any],
    slice_candles: List[Any],
    *,
    analysis_valid: bool,
    rmt_trend: str = "range",
    rmt_leg_count: int = 0,
    rmt_confirmed_leg_count: int = 0,
    structural_level: Optional[Dict[str, Any]] = None,
    attempts: Optional[List[Dict[str, Any]]] = None,
    most_recent_attempt: Optional[Dict[str, Any]] = None,
    most_recent_attempt_result: Optional[str] = None,
    mitigation_count: int = 0,
    rmt_choch_zone: Optional[Dict[str, Any]] = None,
    rmt_choch_proximity: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "rmt_trend": rmt_trend,
        "rmt_leg_count": rmt_leg_count,
        "rmt_confirmed_leg_count": rmt_confirmed_leg_count,
        "structural_level": structural_level,
        "attempts": attempts if attempts is not None else [],
        "attempt_count": len(attempts) if attempts is not None else 0,
        "most_recent_attempt": most_recent_attempt,
        "most_recent_attempt_result": most_recent_attempt_result,
        "mitigation_count": mitigation_count,
        "rmt_choch_zone": rmt_choch_zone,
        "rmt_choch_proximity": rmt_choch_proximity,
        "slice_start_index": int(retracement_leg["start_index"]),
        "slice_end_index": int(retracement_leg["end_index"]),
        "slice_candle_count": len(slice_candles),
        "analysis_valid": analysis_valid,
    }


# Core function. Takes a single confirmed retracement leg and the full candle list.
# Slices the candles to the retracement window, runs identify_trend on the slice,
# finds the structural level, finds all Attempts, classifies the most recent one,
# computes the CHoCH zone for the RMT, and returns a structured analysis result.
# filter_config must contain the six identify_trend filter parameters as keys.
# Returns None if the retracement leg is unconfirmed or the slice is too small.
def analyze_retracement_leg(
    retracement_leg: Dict[str, Any],
    candles: List[Any],
    global_trend: str,
    filter_config: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Analyze a single confirmed retracement leg.

    Args:
        retracement_leg: A confirmed retracement leg dict from identify_trend.
        candles: Full candle list used in the parent trend identification.
        global_trend: Trend direction of the parent context — "up" or "down".
        filter_config: Dict of the six identify_trend filter parameters.

    Returns:
        Analysis result dict or None if the leg is invalid or the slice is too small.
    """
    if not retracement_leg.get("confirmed") or retracement_leg.get("end_index") is None:
        return None

    start_idx = int(retracement_leg["start_index"])
    end_idx = int(retracement_leg["end_index"])
    slice_candles = candles[start_idx : end_idx + 1]

    if len(slice_candles) < 10:
        return None

    rmt_result = identify_trend(slice_candles, **filter_config)

    if rmt_result["trend"] == "range":
        return _build_result(
            retracement_leg, slice_candles, analysis_valid=False, rmt_trend="range"
        )

    all_legs = rmt_result["legs"]
    confirmed_legs = [l for l in all_legs if l.get("confirmed") is True]

    if not confirmed_legs:
        return _build_result(
            retracement_leg,
            slice_candles,
            analysis_valid=False,
            rmt_trend=rmt_result["trend"],
            rmt_leg_count=len(all_legs),
        )

    structural_level = find_rmt_structural_level(rmt_result, global_trend)

    if structural_level is None:
        return _build_result(
            retracement_leg,
            slice_candles,
            analysis_valid=False,
            rmt_trend=rmt_result["trend"],
            rmt_leg_count=len(all_legs),
            rmt_confirmed_leg_count=len(confirmed_legs),
        )

    attempts = find_attempts(rmt_result, structural_level, global_trend)
    most_recent_attempt = attempts[-1] if attempts else None
    most_recent_attempt_result = (
        most_recent_attempt["attempt_result"] if most_recent_attempt else None
    )
    mitigation_count = sum(1 for a in attempts if a["attempt_result"] == "false_break")

    rmt_choch = get_active_choch_zone(rmt_result["legs"], rmt_result["trend"], slice_candles)

    current_price_in_rmt = float(candles[end_idx].close)
    rmt_choch_proximity = None
    if rmt_choch is not None:
        rmt_choch_proximity = compute_choch_proximity(
            rmt_choch["choch_zone"], current_price_in_rmt
        )

    return _build_result(
        retracement_leg,
        slice_candles,
        analysis_valid=True,
        rmt_trend=rmt_result["trend"],
        rmt_leg_count=len(all_legs),
        rmt_confirmed_leg_count=len(confirmed_legs),
        structural_level=structural_level,
        attempts=attempts,
        most_recent_attempt=most_recent_attempt,
        most_recent_attempt_result=most_recent_attempt_result,
        mitigation_count=mitigation_count,
        rmt_choch_zone=rmt_choch["choch_zone"] if rmt_choch else None,
        rmt_choch_proximity=rmt_choch_proximity,
    )


# Entry point for downstream use. Takes the full candle list and the result
# from identify_trend (already computed by the pipeline — not recomputed here).
# Finds the current retracement leg: if current_phase == "retracement", uses
# the last confirmed retracement leg. If current_phase == "impulse", uses the
# most recent confirmed retracement leg before the current impulse.
# Returns None if no confirmed retracement leg exists.
def analyze_current_retracement(
    candles: List[Any],
    result: Dict[str, Any],
    filter_config: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Entry point — analyze the most recent confirmed retracement in the trend.

    Args:
        candles: Full candle list.
        result: Result dict from identify_trend (already computed externally).
        filter_config: Dict of the six identify_trend filter parameters.

    Returns:
        Enriched analysis dict or None if no confirmed retracement leg exists.
    """
    global_trend = result["trend"]

    confirmed_retracements = [
        leg
        for leg in result["legs"]
        if leg.get("type") == "retracement" and leg.get("confirmed") is True
    ]

    if not confirmed_retracements:
        return None

    target_leg = confirmed_retracements[-1]
    leg_index = result["legs"].index(target_leg)

    analysis = analyze_retracement_leg(target_leg, candles, global_trend, filter_config)

    if analysis is not None:
        analysis["global_trend"] = global_trend
        analysis["retracement_leg_index"] = leg_index

    return analysis
