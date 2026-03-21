"""Recursive structural depth walker for Chronos-AI.

Pure stateless module. No side effects. No file I/O.

Design decision — avoiding double identify_trend calls:
  _walk_level does NOT call analyze_retracement_leg (which would run identify_trend
  internally). Instead, _walk_level runs identify_trend exactly once per level and
  then delegates to a local helper (_build_analysis_from_rmt) that builds the
  analysis dict directly from the already-computed rmt_result. This avoids the
  double-computation that would result from calling analyze_retracement_leg followed
  by a second identify_trend for find_response_move.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.core.choch_zone import compute_choch_proximity, get_active_choch_zone
from src.core.retracement_analysis import find_attempts, find_rmt_structural_level
from src.core.trend_id import identify_trend

# ------------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------------


def _build_analysis_dict(
    retracement_leg: Dict[str, Any],
    slice_candles: List[Any],
    current_price: float,
    rmt_result: Dict[str, Any],
    global_trend: str,
) -> Dict[str, Any]:
    """Build the same-schema analysis dict as analyze_retracement_leg but from a
    pre-computed rmt_result, so identify_trend is never called twice per level."""
    all_legs = rmt_result["legs"]
    confirmed_legs = [l for l in all_legs if l.get("confirmed") is True]

    base = {
        "rmt_trend": rmt_result["trend"],
        "rmt_leg_count": len(all_legs),
        "rmt_confirmed_leg_count": len(confirmed_legs),
        "structural_level": None,
        "attempts": [],
        "attempt_count": 0,
        "most_recent_attempt": None,
        "most_recent_attempt_result": None,
        "mitigation_count": 0,
        "rmt_choch_zone": None,
        "rmt_choch_proximity": None,
        "slice_start_index": int(retracement_leg["start_index"]),
        "slice_end_index": int(retracement_leg["end_index"]),
        "slice_candle_count": len(slice_candles),
        "analysis_valid": False,
    }

    if not confirmed_legs:
        return base

    structural_level = find_rmt_structural_level(rmt_result, global_trend)
    if structural_level is None:
        return base

    attempts = find_attempts(rmt_result, structural_level, global_trend)
    most_recent_attempt = attempts[-1] if attempts else None
    mitigation_count = sum(1 for a in attempts if a["attempt_result"] == "false_break")

    rmt_choch = get_active_choch_zone(rmt_result["legs"], rmt_result["trend"], slice_candles)

    rmt_choch_proximity = None
    if rmt_choch is not None:
        rmt_choch_proximity = compute_choch_proximity(
            rmt_choch["choch_zone"], current_price
        )

    base.update(
        {
            "structural_level": structural_level,
            "attempts": attempts,
            "attempt_count": len(attempts),
            "most_recent_attempt": most_recent_attempt,
            "most_recent_attempt_result": (
                most_recent_attempt["attempt_result"] if most_recent_attempt else None
            ),
            "mitigation_count": mitigation_count,
            "rmt_choch_zone": rmt_choch["choch_zone"] if rmt_choch else None,
            "rmt_choch_proximity": rmt_choch_proximity,
            "analysis_valid": True,
        }
    )
    return base


def _build_waiting_for(deepest_level: Dict[str, Any]) -> str:
    """Construct the human-readable waiting_for message from the deepest level."""
    reason = deepest_level.get("termination_reason") or "invalid_analysis"
    analysis = deepest_level.get("analysis") or {}

    if reason == "no_attempt_found":
        structural_level = analysis.get("structural_level")
        price = structural_level["price"] if structural_level else "unknown"
        return f"Waiting for retracement to reach structural level at {price}"

    if reason == "waiting_for_response_move":
        most_recent = analysis.get("most_recent_attempt")
        attempt_result = most_recent["attempt_result"] if most_recent else "unknown"
        price = most_recent["end_price"] if most_recent else "unknown"
        return f"Waiting for response move after {attempt_result} attempt at {price}"

    if reason == "max_depth_reached":
        return "Maximum analysis depth reached — monitor active CHoCH zone"

    if reason == "child_slice_too_small":
        return "Price action too compressed for further analysis"

    return "Insufficient structure in current retracement"


def _empty_analysis(retracement_leg: Dict[str, Any], slice_candles: List[Any], rmt_leg_count: int = 0) -> Dict[str, Any]:
    return {
        "rmt_trend": "range",
        "rmt_leg_count": rmt_leg_count,
        "rmt_confirmed_leg_count": 0,
        "structural_level": None,
        "attempts": [],
        "attempt_count": 0,
        "most_recent_attempt": None,
        "most_recent_attempt_result": None,
        "mitigation_count": 0,
        "rmt_choch_zone": None,
        "rmt_choch_proximity": None,
        "slice_start_index": int(retracement_leg["start_index"]),
        "slice_end_index": int(retracement_leg["end_index"]),
        "slice_candle_count": len(slice_candles),
        "analysis_valid": False,
    }


# ------------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------------


# Finds the Response Move — the retracement leg within the RMT that started
# after the most recent Attempt and represents the market moving back toward
# the RMT's CHoCH zone after failing to break or having broken structure.
# The Response Move is the next confirmed retracement leg after the Attempt leg.
# Returns None if no such leg exists (system is waiting for the market to move).
def find_response_move(
    rmt_result: Dict[str, Any],
    most_recent_attempt: Dict[str, Any],
    global_trend: str,
) -> Optional[Dict[str, Any]]:
    """Find the first confirmed retracement leg after the most recent Attempt.

    Args:
        rmt_result: Result dict from identify_trend on the retracement slice.
        most_recent_attempt: Attempt dict from find_attempts (must have leg_index).
        global_trend: Trend direction of the parent context — "up" or "down".

    Returns:
        Dict with leg metadata relative to the RMT slice, or None.
    """
    _ = global_trend  # Reserved for future directional response constraints.
    legs = rmt_result["legs"]
    start_search = most_recent_attempt["leg_index"] + 1

    for j in range(start_search, len(legs)):
        cand = legs[j]
        if (
            cand.get("type") == "retracement"
            and cand.get("confirmed") is True
        ):
            end_index = cand.get("end_index")
            return {
                "leg_index": j,
                "start_index": int(cand["start_index"]),
                "end_index": int(end_index) if end_index is not None else None,
                "start_price": float(cand["start_price"]),
                "end_price": float(cand["end_price"]) if cand.get("end_price") is not None else None,
                "confirmed": True,
            }

    return None


# Recursive walker. At each depth level:
# 1. Runs analyze_retracement_leg on the given retracement leg
# 2. Finds the Response Move after the most recent Attempt
# 3. If Response Move exists and depth limit not reached, recurses
# 4. Returns a level dict containing the analysis, response move, and child levels
# global_offset: the start_index of this slice relative to the full candle list.
#                Used so all indices can be converted to global space by callers.
def _walk_level(
    candles: List[Any],
    retracement_leg: Dict[str, Any],
    global_trend: str,
    filter_config: Dict[str, Any],
    current_depth: int,
    max_depth: int,
    global_offset: int,
) -> Dict[str, Any]:
    """Recursive implementation of the structural depth walk.

    Args:
        candles: Full global candle list.
        retracement_leg: Leg dict with indices RELATIVE to this level's slice.
        global_trend: Parent trend direction — "up" or "down".
        filter_config: The six identify_trend filter parameters as a dict.
        current_depth: Recursion depth, starting at 1.
        max_depth: Maximum permitted depth.
        global_offset: Global candle index where this level's slice begins.

    Returns:
        Level dict with depth, global_offset, analysis, response_move, child.
    """
    level_dict: Dict[str, Any] = {
        "depth": current_depth,
        "global_offset": global_offset,
        "retracement_leg": retracement_leg,
        "analysis": None,
        "response_move": None,
        "child": None,
        "termination_reason": None,
    }

    # Validate the retracement leg
    if not retracement_leg.get("confirmed") or retracement_leg.get("end_index") is None:
        level_dict["analysis"] = None
        level_dict["termination_reason"] = "invalid_analysis"
        return level_dict

    rel_start_idx = int(retracement_leg["start_index"])
    rel_end_idx = int(retracement_leg["end_index"])
    start_idx = global_offset + rel_start_idx
    end_idx = global_offset + rel_end_idx
    slice_candles = candles[start_idx : end_idx + 1]

    if len(slice_candles) < 10:
        level_dict["analysis"] = None
        level_dict["termination_reason"] = "child_slice_too_small"
        return level_dict

    # Run identify_trend exactly once for this level (see module docstring).
    rmt_result = identify_trend(slice_candles, **filter_config)

    # NOTE: rmt_result["legs"] indices are relative to this level's slice.
    # To get global candle indices, add layer_start_index to each leg index.
    level_dict["layer_start_index"] = global_offset + int(retracement_leg["start_index"])
    level_dict["layer_end_index"] = (
        global_offset + int(retracement_leg["end_index"])
        if retracement_leg.get("end_index") is not None
        else None
    )
    level_dict["rmt_result"] = rmt_result

    if rmt_result["trend"] == "range":
        level_dict["analysis"] = _empty_analysis(
            retracement_leg,
            slice_candles,
            rmt_leg_count=len(rmt_result["legs"]),
        )
        level_dict["termination_reason"] = "invalid_analysis"
        return level_dict

    analysis = _build_analysis_dict(
        retracement_leg,
        slice_candles,
        current_price=float(candles[end_idx].close),
        rmt_result=rmt_result,
        global_trend=global_trend,
    )
    level_dict["analysis"] = analysis

    if not analysis["analysis_valid"]:
        level_dict["termination_reason"] = "invalid_analysis"
        return level_dict

    most_recent_attempt = analysis["most_recent_attempt"]
    if most_recent_attempt is None:
        level_dict["termination_reason"] = "no_attempt_found"
        return level_dict

    response_move = find_response_move(rmt_result, most_recent_attempt, global_trend)
    level_dict["response_move"] = response_move

    if response_move is None:
        level_dict["termination_reason"] = "waiting_for_response_move"
        return level_dict

    if current_depth >= max_depth:
        level_dict["termination_reason"] = "max_depth_reached"
        return level_dict

    # Build child slice indices in global space.
    # child_start_global is a global candle index — passed as global_offset to the
    # recursive call so the child level can compute its own layer_start_index correctly.
    child_start_global = global_offset + response_move["start_index"]
    child_end_global = (
        global_offset + response_move["end_index"]
        if response_move["end_index"] is not None
        else len(candles) - 1
    )

    if child_end_global - child_start_global < 9:  # < 10 candles
        level_dict["termination_reason"] = "child_slice_too_small"
        return level_dict

    # Child leg indices are relative to the child slice by invariant.
    child_len = child_end_global - child_start_global + 1
    child_leg: Dict[str, Any] = {
        "type": "retracement",
        "start_index": 0,
        "end_index": child_len - 1,
        "start_price": response_move["start_price"],
        "end_price": response_move["end_price"],
        "confirmed": True,
        "slope": None,
    }

    level_dict["child"] = _walk_level(
        candles,
        child_leg,
        global_trend,
        filter_config,
        current_depth + 1,
        max_depth,
        child_start_global,
    )
    return level_dict


# Primary entry point. Takes the full candle list and the already-computed
# identify_trend result (never recomputed here — passed in from the pipeline).
# Finds the current retracement leg, initiates the recursive walk, and
# returns the complete State Report.
# max_depth: maximum recursion levels (default 4, configurable).
# filter_config: the six identify_trend filter parameters as a dict.
def walk_structure(
    candles: List[Any],
    result: Dict[str, Any],
    filter_config: Dict[str, Any],
    max_depth: int = 4,
) -> Dict[str, Any]:
    """Recursive structural depth walk — primary entry point.

    Args:
        candles: Full candle list.
        result: Dict from identify_trend (not recomputed here).
        filter_config: The six identify_trend filter parameters as a dict.
        max_depth: Maximum recursion depth (default 4).

    Returns:
        Complete State Report dict.
    """
    global_trend = result.get("trend", "range")

    def _not_walkable(reason: str) -> Dict[str, Any]:
        return {
            "walkable": False,
            "reason": reason,
            "global_trend": global_trend,
            "levels": [],
            "max_depth_reached": 0,
            "total_mitigation_count": 0,
            "deepest_termination_reason": reason,
            "active_level": 0,
            "active_choch_zone": None,
            "active_choch_proximity": None,
            "waiting_for": "Insufficient structure in current retracement",
            "stars_aligned": False,
        }

    if global_trend == "range":
        return _not_walkable("global_trend_is_range")

    confirmed_retracements = [
        leg
        for leg in result.get("legs", [])
        if leg.get("type") == "retracement" and leg.get("confirmed") is True
    ]

    if not confirmed_retracements:
        return _not_walkable("no_confirmed_retracement")

    root_leg_global = confirmed_retracements[-1]
    root_start = int(root_leg_global["start_index"])
    root_end = int(root_leg_global["end_index"])
    root_leg_relative = {
        "type": "retracement",
        "start_index": 0,
        "end_index": root_end - root_start,
        "start_price": root_leg_global["start_price"],
        "end_price": root_leg_global["end_price"],
        "confirmed": root_leg_global.get("confirmed", False),
        "slope": root_leg_global.get("slope"),
    }

    root_level = _walk_level(
        candles,
        root_leg_relative,
        global_trend,
        filter_config,
        current_depth=1,
        max_depth=max_depth,
        global_offset=root_start,
    )

    # Flatten the child chain into a levels list
    levels: List[Dict[str, Any]] = []
    current = root_level
    while current is not None:
        levels.append(current)
        current = current.get("child")

    # Compute summary fields
    max_depth_reached = max(
        (
            lvl["depth"]
            for lvl in levels
            if lvl.get("analysis") and lvl["analysis"].get("analysis_valid")
        ),
        default=0,
    )

    total_mitigation_count = sum(
        lvl["analysis"].get("mitigation_count", 0)
        for lvl in levels
        if lvl.get("analysis") and lvl["analysis"].get("analysis_valid")
    )

    deepest_level = levels[-1] if levels else root_level
    deepest_termination_reason = deepest_level.get("termination_reason") or "unknown"

    active_level_index = 0
    active_level_depth = 0
    for i, lvl in enumerate(levels):
        if lvl.get("analysis") and lvl["analysis"].get("analysis_valid"):
            active_level_index = i
            active_level_depth = lvl["depth"]

    active_analysis = levels[active_level_index].get("analysis") if levels else None
    active_choch_zone = active_analysis.get("rmt_choch_zone") if active_analysis else None
    active_choch_proximity = active_analysis.get("rmt_choch_proximity") if active_analysis else None

    waiting_for = _build_waiting_for(deepest_level)

    return {
        "walkable": True,
        "reason": None,
        "global_trend": global_trend,
        "levels": levels,
        "max_depth_reached": max_depth_reached,
        "total_mitigation_count": total_mitigation_count,
        "deepest_termination_reason": deepest_termination_reason,
        "active_level": active_level_depth,
        "active_choch_zone": active_choch_zone,
        "active_choch_proximity": active_choch_proximity,
        "waiting_for": waiting_for,
        "stars_aligned": False,  # Set by Phase 4
    }
