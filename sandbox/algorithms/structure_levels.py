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

from copy import deepcopy
from typing import Any, Dict, List, Optional

from choch_zone import compute_choch_zone


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


def classify_bos_events(
    legs: List[Dict[str, Any]],
    trend: str,
    false_break_retrace_ratio: float = 0.60,
) -> List[Dict[str, Any]]:
    """Classify each BOS level as true, false, pending, or invalid.

    A BOS level is the end price of a confirmed impulse. It is considered broken
    by the *next* confirmed impulse if that later impulse exceeds the prior
    impulse endpoint in the trend direction. The break is then classified by the
    size of the next confirmed retracement relative to the breaking impulse.
    """
    if trend not in {"up", "down"}:
        return []

    confirmed_impulses: List[tuple[int, Dict[str, Any]]] = []
    for leg_index, leg in enumerate(legs):
        if (
            leg.get("type") == "impulse"
            and leg.get("confirmed") is True
            and leg.get("start_price") is not None
            and leg.get("end_price") is not None
            and leg.get("start_index") is not None
            and leg.get("end_index") is not None
        ):
            confirmed_impulses.append((leg_index, leg))

    events: List[Dict[str, Any]] = []
    for impulse_idx, (source_leg_index, source_leg) in enumerate(confirmed_impulses):
        event: Dict[str, Any] = {
            "source_impulse_leg_index": int(source_leg_index),
            "source_impulse_start_index": int(source_leg["start_index"]),
            "source_impulse_end_index": int(source_leg["end_index"]),
            "source_impulse_end_timestamp": source_leg.get("end_timestamp"),
            "bos_price": float(source_leg["end_price"]),
            "status": "pending",
            "breaking_impulse_leg_index": None,
            "breaking_impulse_start_index": None,
            "breaking_impulse_end_index": None,
            "breaking_impulse_end_timestamp": None,
            "breaking_impulse_size": None,
            "next_retracement_leg_index": None,
            "next_retracement_start_index": None,
            "next_retracement_end_index": None,
            "next_retracement_end_timestamp": None,
            "next_retracement_size": None,
            "retracement_ratio": None,
            "false_break_retrace_ratio": float(false_break_retrace_ratio),
        }

        if impulse_idx + 1 >= len(confirmed_impulses):
            events.append(event)
            continue

        breaking_leg_index, breaking_leg = confirmed_impulses[impulse_idx + 1]
        source_price = float(source_leg["end_price"])
        breaking_price = float(breaking_leg["end_price"])
        did_break = (
            breaking_price > source_price if trend == "up" else breaking_price < source_price
        )

        event.update({
            "breaking_impulse_leg_index": int(breaking_leg_index),
            "breaking_impulse_start_index": int(breaking_leg["start_index"]),
            "breaking_impulse_end_index": int(breaking_leg["end_index"]),
            "breaking_impulse_end_timestamp": breaking_leg.get("end_timestamp"),
            "breaking_impulse_size": abs(float(breaking_leg["end_price"]) - float(breaking_leg["start_price"])),
        })

        if not did_break:
            event["status"] = "invalid"
            events.append(event)
            continue

        next_retracement_index = None
        next_retracement_leg = None
        for probe_index in range(breaking_leg_index + 1, len(legs)):
            probe = legs[probe_index]
            if probe.get("type") == "retracement" and probe.get("confirmed") is True and probe.get("start_price") is not None and probe.get("end_price") is not None:
                next_retracement_index = probe_index
                next_retracement_leg = probe
                break
            if probe.get("type") == "impulse" and probe.get("confirmed") is True:
                break

        if next_retracement_leg is None or next_retracement_index is None:
            events.append(event)
            continue

        retracement_size = abs(float(next_retracement_leg["end_price"]) - float(next_retracement_leg["start_price"]))
        impulse_size = float(event["breaking_impulse_size"] or 0.0)
        retracement_ratio = (retracement_size / impulse_size) if impulse_size > 0 else None

        event.update({
            "next_retracement_leg_index": int(next_retracement_index),
            "next_retracement_start_index": int(next_retracement_leg["start_index"]),
            "next_retracement_end_index": int(next_retracement_leg["end_index"]),
            "next_retracement_end_timestamp": next_retracement_leg.get("end_timestamp"),
            "next_retracement_size": retracement_size,
            "retracement_ratio": retracement_ratio,
            "status": "false" if retracement_ratio is not None and retracement_ratio >= false_break_retrace_ratio else "true",
        })
        events.append(event)

    return events


def annotate_internal_bos_classifications(
    legs: List[Dict[str, Any]],
    false_break_retrace_ratio: float = 0.60,
) -> List[Dict[str, Any]]:
    """Attach BOS classifications for each impulse leg's internal structure."""
    for leg in legs:
        leg["internal_bos_classifications"] = []
        internal = leg.get("internal_structure") or {}
        internal_legs = internal.get("legs") or []
        internal_trend = internal.get("trend")
        if internal_legs and internal_trend in {"up", "down"}:
            leg["internal_bos_classifications"] = classify_bos_events(
                internal_legs,
                internal_trend,
                false_break_retrace_ratio=false_break_retrace_ratio,
            )
    return legs


def extract_false_break_impulses(
    legs: List[Dict[str, Any]],
    trend: str,
    false_break_retrace_ratio: float = 0.60,
) -> List[Dict[str, Any]]:
    """Return copies of impulses whose BOS classification is false."""
    false_impulses: List[Dict[str, Any]] = []
    for event in classify_bos_events(
        legs,
        trend,
        false_break_retrace_ratio=false_break_retrace_ratio,
    ):
        if event.get("status") != "false":
            continue
        breaking_index = event.get("breaking_impulse_leg_index")
        if breaking_index is None or breaking_index < 0 or breaking_index >= len(legs):
            continue
        impulse_copy = deepcopy(legs[breaking_index])
        impulse_copy["false_break_event"] = deepcopy(event)
        false_impulses.append(impulse_copy)
    return false_impulses


def collapse_false_break_impulses(
    legs: List[Dict[str, Any]],
    trend: str,
    false_break_retrace_ratio: float = 0.60,
    max_iterations: int = 20,
) -> Dict[str, Any]:
    """Collapse false-break impulses into the prior valid impulse.

    For each false BOS event, the prior source impulse is extended to the false
    breaking impulse's extreme. The intermediate retracement and the false
    breaking impulse are removed from the active structure. The process is
    repeated until no false BOS remains or max_iterations is reached.
    """
    cleaned_legs: List[Dict[str, Any]] = deepcopy(legs)
    absorbed_false_impulses: List[Dict[str, Any]] = []
    history: List[Dict[str, Any]] = []

    for iteration in range(max_iterations):
        classifications = classify_bos_events(
            cleaned_legs,
            trend,
            false_break_retrace_ratio=false_break_retrace_ratio,
        )
        false_event = next(
            (event for event in classifications if event.get("status") == "false"),
            None,
        )
        if false_event is None:
            return {
                "legs": cleaned_legs,
                "false_impulses": absorbed_false_impulses,
                "history": history,
                "iterations": iteration,
                "classifications": classifications,
            }

        source_index = false_event.get("source_impulse_leg_index")
        breaking_index = false_event.get("breaking_impulse_leg_index")
        if (
            source_index is None
            or breaking_index is None
            or source_index < 0
            or breaking_index <= source_index
            or breaking_index >= len(cleaned_legs)
        ):
            break

        source_leg = deepcopy(cleaned_legs[source_index])
        breaking_leg = deepcopy(cleaned_legs[breaking_index])
        absorbed_segment = deepcopy(cleaned_legs[source_index + 1 : breaking_index + 1])

        source_leg["end_index"] = breaking_leg.get("end_index")
        source_leg["end_price"] = breaking_leg.get("end_price")
        if "end_timestamp" in breaking_leg:
            source_leg["end_timestamp"] = breaking_leg.get("end_timestamp")
        source_leg["absorbed_false_break_count"] = int(
            source_leg.get("absorbed_false_break_count", 0)
        ) + 1
        absorbed_markers = list(source_leg.get("absorbed_false_breaks") or [])
        absorbed_markers.append(
            {
                "iteration": iteration + 1,
                "breaking_impulse_start_index": breaking_leg.get("start_index"),
                "breaking_impulse_end_index": breaking_leg.get("end_index"),
                "breaking_impulse_start_price": breaking_leg.get("start_price"),
                "breaking_impulse_end_price": breaking_leg.get("end_price"),
                "retracement_ratio": false_event.get("retracement_ratio"),
            }
        )
        source_leg["absorbed_false_breaks"] = absorbed_markers

        suffix = deepcopy(cleaned_legs[breaking_index + 1 :])
        if suffix:
            suffix[0]["start_index"] = source_leg.get("end_index")
            suffix[0]["start_price"] = source_leg.get("end_price")
            if source_leg.get("end_timestamp") is not None:
                suffix[0]["start_timestamp"] = source_leg.get("end_timestamp")

        absorbed_false_impulses.append(
            {
                "iteration": iteration + 1,
                "event": deepcopy(false_event),
                "source_impulse": deepcopy(cleaned_legs[source_index]),
                "breaking_impulse": breaking_leg,
                "absorbed_segment": absorbed_segment,
                "merged_impulse": deepcopy(source_leg),
            }
        )
        history.append(
            {
                "iteration": iteration + 1,
                "source_impulse_leg_index": source_index,
                "breaking_impulse_leg_index": breaking_index,
                "removed_leg_count": len(absorbed_segment),
                "remaining_leg_count": len(cleaned_legs) - len(absorbed_segment),
            }
        )
        cleaned_legs = (
            deepcopy(cleaned_legs[:source_index])
            + [source_leg]
            + suffix
        )

    return {
        "legs": cleaned_legs,
        "false_impulses": absorbed_false_impulses,
        "history": history,
        "iterations": len(history),
        "classifications": classify_bos_events(
            cleaned_legs,
            trend,
            false_break_retrace_ratio=false_break_retrace_ratio,
        ),
        "hit_iteration_limit": True,
    }


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
