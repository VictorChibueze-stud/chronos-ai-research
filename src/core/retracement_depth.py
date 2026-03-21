"""Retracement depth helpers built from trend_id leg output.

This module is pure and stateless: it consumes leg dictionaries and returns
computed retracement depth metadata without side effects.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict, cast


class RetracementDepth(TypedDict):
    impulse_start: float
    impulse_end: float
    impulse_range: float
    retracement_start: float
    retracement_end: Optional[float]
    retracement_move: float
    depth_ratio: float
    depth_pct: float
    exceeds_impulse: bool
    confirmed: bool


class RetracementDepthSummary(TypedDict):
    count: int
    depths_pct: List[float]
    mean_depth_pct: float
    min_depth_pct: float
    max_depth_pct: float
    any_exceeds_impulse: bool


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


# Measures how much of the preceding impulse was retraced, as a ratio and percentage.
# depth_ratio=0.40 means the retracement gave back 40% of the preceding impulse range.
# depth_ratio > 1.0 means the retracement exceeded the impulse - CHoCH territory.
# Use this for historical analysis: avg retracement depth per asset, timeframe, trend phase.
def compute_retracement_depth(
    retracement_leg: Dict[str, Any],
    preceding_impulse_leg: Dict[str, Any],
) -> Optional[RetracementDepth]:
    impulse_start_raw = preceding_impulse_leg.get("start_price")
    impulse_end_raw = preceding_impulse_leg.get("end_price")
    retracement_start_raw = retracement_leg.get("start_price")

    if impulse_start_raw is None or impulse_end_raw is None or retracement_start_raw is None:
        return None

    impulse_start = float(impulse_start_raw)
    impulse_end = float(impulse_end_raw)
    impulse_range = abs(impulse_end - impulse_start)
    if impulse_range == 0.0:
        return None

    retracement_end_raw = retracement_leg.get("end_price")
    if retracement_end_raw is None:
        retracement_end = None
        retracement_move = 0.0
        confirmed = False
    else:
        retracement_end = float(retracement_end_raw)
        retracement_move = abs(retracement_end - float(retracement_start_raw))
        confirmed = bool(retracement_leg.get("confirmed") is True)

    depth_ratio = _clamp(retracement_move / impulse_range, 0.0, 1.5)
    depth_pct = round(depth_ratio * 100.0, 1)

    return {
        "impulse_start": impulse_start,
        "impulse_end": impulse_end,
        "impulse_range": impulse_range,
        "retracement_start": float(retracement_start_raw),
        "retracement_end": retracement_end,
        "retracement_move": retracement_move,
        "depth_ratio": depth_ratio,
        "depth_pct": depth_pct,
        "exceeds_impulse": depth_ratio > 1.0,
        "confirmed": confirmed,
    }


def annotate_legs_with_depth(legs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for index, leg in enumerate(legs):
        leg["retracement_depth"] = None

        if leg.get("type") != "retracement":
            continue

        previous_leg = legs[index - 1] if index > 0 else None
        if (
            previous_leg is None
            or previous_leg.get("type") != "impulse"
            or previous_leg.get("confirmed") is not True
            or previous_leg.get("start_price") is None
            or previous_leg.get("end_price") is None
        ):
            continue

        depth = compute_retracement_depth(leg, previous_leg)
        leg["retracement_depth"] = depth

    return legs


# Aggregate summary of all retracement depths in a trend.
# Use mean_depth_pct to answer: "how deep does this asset typically retrace?"
# Use any_exceeds_impulse to flag CHoCH risk on the current trend.
def summarise_retracement_depths(legs: List[Dict[str, Any]]) -> Optional[RetracementDepthSummary]:
    confirmed_depths: List[RetracementDepth] = []
    for leg in legs:
        depth = leg.get("retracement_depth")
        if isinstance(depth, dict) and depth.get("confirmed") is True:
            confirmed_depths.append(cast(RetracementDepth, depth))

    if not confirmed_depths:
        return None

    depths_pct = [float(depth["depth_pct"]) for depth in confirmed_depths]

    return {
        "count": len(depths_pct),
        "depths_pct": depths_pct,
        "mean_depth_pct": round(sum(depths_pct) / len(depths_pct), 1),
        "min_depth_pct": min(depths_pct),
        "max_depth_pct": max(depths_pct),
        "any_exceeds_impulse": any(bool(depth["exceeds_impulse"]) for depth in confirmed_depths),
    }
