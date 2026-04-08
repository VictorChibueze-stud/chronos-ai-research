"""Structure level helpers built from trend_id leg output.

This module is additive: it consumes candles/legs/trend output produced elsewhere
without modifying any trend detection behavior.
"""

# TODO: implement analyze_impulse_as_trend(candles, impulse_leg) -> dict
# Takes a single confirmed impulse leg and the full candle list.
# Slices candles to the impulse window, treats it as a standalone trend,
# runs identify_trend + compute_all_structure_levels on the slice,
# and returns the full internal zigzag with BOS and CHoCH levels.
# This is the foundation for recursive fractal analysis.

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.core.choch_zone import compute_choch_zone


def _opposite_break(close_price: float, level_price: float, trend_direction: str) -> bool:
    """Return True when close crosses the level opposite to the trend direction."""
    if trend_direction == "down":
        return close_price > level_price
    return close_price < level_price


def compute_bos_levels(candles: List[Any], legs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compute BOS horizontal levels from confirmed impulse leg ends.

    The line starts at the impulse end index and extends right until an opposite
    close break is observed, or until the final candle.
    """
    if not candles:
        return []

    last_index = len(candles) - 1
    bos_levels: List[Dict[str, Any]] = []

    for leg in legs:
        if (
            leg.get("type") != "impulse"
            or leg.get("confirmed") is not True
            or leg.get("end_index") is None
            or leg.get("end_price") is None
        ):
            continue

        level_price = leg["end_price"]
        start_index = leg["end_index"]
        trend_direction = "down" if leg["end_price"] <= leg["start_price"] else "up"
        broken = False
        break_index: Optional[int] = None

        for index in range(start_index + 1, len(candles)):
            if _opposite_break(candles[index].close, level_price, trend_direction):
                broken = True
                break_index = index
                break

        bos_levels.append(
            {
                "price": float(level_price),
                "start_index": int(start_index),
                "end_index": int(last_index),
                "broken": broken,
                "trend_direction": trend_direction,
                "break_index": break_index,
            }
        )

    return bos_levels


def compute_choch_level(
    candles: List[Any], legs: List[Dict[str, Any]], trend: str
) -> Optional[Dict[str, Any]]:
    """Compute CHoCH horizontal level from the most recent confirmed impulse start."""
    if not candles:
        return None

    confirmed_impulses = [
        leg
        for leg in legs
        if (
            leg.get("type") == "impulse"
            and leg.get("confirmed") is True
            and leg.get("start_index") is not None
            and leg.get("start_price") is not None
        )
    ]
    if len(confirmed_impulses) < 2:
        return None

    latest_impulse = confirmed_impulses[-1]
    level_price = latest_impulse["start_price"]
    start_index = latest_impulse["start_index"]
    broken = False

    for index in range(start_index + 1, len(candles)):
        if _opposite_break(candles[index].close, level_price, trend):
            broken = True
            break

    return {
        "price": float(level_price),
        "start_index": int(start_index),
        "end_index": int(len(candles) - 1),
        "broken": broken,
        "trend_direction": trend,
    }


def compute_internal_structure_levels(candles: List[Any], legs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compute internal BOS/CHoCH levels for each confirmed global impulse.

    Mutates legs in place by attaching:
    - leg["internal_bos_levels"]
    - leg["internal_choch_level"]
    """
    for leg in legs:
        leg["internal_bos_levels"] = []
        leg["internal_choch_level"] = None

        if (
            leg.get("type") != "impulse"
            or leg.get("confirmed") is not True
            or leg.get("start_index") is None
            or leg.get("end_index") is None
        ):
            continue

        internal = leg.get("internal_structure")
        if internal is None:
            continue

        internal_legs = internal.get("legs") or []
        internal_trend = internal.get("trend")
        if not internal_legs or internal_trend not in {"up", "down"}:
            continue

        parent_start = leg["start_index"]
        parent_end = leg["end_index"]
        slice_candles = candles[parent_start : parent_end + 1]
        if not slice_candles:
            continue

        internal_bos_levels = compute_bos_levels(slice_candles, internal_legs)
        internal_choch_level = compute_choch_level(slice_candles, internal_legs, internal_trend)

        for bos in internal_bos_levels:
            bos["start_index"] += parent_start
            bos["end_index"] = len(candles) - 1
            bi = bos.get("break_index")
            if bi is not None:
                bos["break_index"] = int(bi) + parent_start

        if internal_choch_level is not None:
            internal_choch_level["start_index"] += parent_start
            internal_choch_level["end_index"] = len(candles) - 1

        leg["internal_bos_levels"] = internal_bos_levels
        leg["internal_choch_level"] = internal_choch_level

    return legs


def compute_all_structure_levels(
    candles: List[Any], legs: List[Dict[str, Any]], trend: str
) -> Dict[str, Any]:
    """Compute both BOS and CHoCH levels in a single payload."""
    return {
        "bos_levels": compute_bos_levels(candles, legs),
        "choch_level": compute_choch_level(candles, legs, trend),
    }


def compute_last_impulse_internal_choch_zone(
    candles: List[Any],
    legs: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """CHoCH zone for the most recent confirmed global impulse's internal trend.

    Returns a dict with zone bounds and global candle index for horizontal start,
    or None if internal structure or zone is unavailable.
    """
    if not candles or not legs:
        return None

    confirmed_impulses = [
        leg
        for leg in legs
        if (
            leg.get("type") == "impulse"
            and leg.get("confirmed") is True
            and leg.get("end_index") is not None
        )
    ]
    if not confirmed_impulses:
        return None

    leg = confirmed_impulses[-1]
    internal = leg.get("internal_structure") or {}
    internal_trend = internal.get("trend")
    internal_legs = internal.get("legs") or []
    if internal_trend not in {"up", "down"} or not internal_legs:
        return None

    zone = compute_choch_zone(internal_legs, internal_trend)
    if zone is None:
        return None

    parent_start = int(leg["start_index"])
    src_internal = int(zone["source_impulse_start_index"])
    global_src = parent_start + src_internal
    n = len(candles)
    if global_src < 0 or global_src >= n:
        return None

    internal_choch_level = leg.get("internal_choch_level")
    broken = bool(internal_choch_level.get("broken")) if isinstance(internal_choch_level, dict) else False

    return {
        "lower_boundary": float(zone["lower_boundary"]),
        "upper_boundary": float(zone["upper_boundary"]),
        "source_impulse_start_index_global": global_src,
        "trend_direction": internal_trend,
        "broken": broken,
    }
