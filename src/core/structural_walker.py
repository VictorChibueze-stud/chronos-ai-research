"""Recursive structural depth walker for Ikenga.

Depth model:
- A new depth level is created only when a trend that started from the prior
  depth's CHoCH zone crosses that prior depth's BOS (structural level).
- That crossing trend slice becomes the next depth input.

Pure stateless module. No side effects. No file I/O.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.core.choch_zone import get_active_choch_zone
from src.core.trend_id import (
    identify_trend,
    compute_internal_structure,
    _collect_candidates,
    _score_candidates,
)

RMT_DEFAULT_FILTER_CONFIG = {
    "use_parent_relative_filter": False,
    "min_impulse_parent_ratio": 0.15,
    "use_momentum_filter": False,
    "min_momentum_ratio": 0.3,
    "use_dominance_filter": False,
    "min_dominance_ratio": 1.2,
}

_DEFAULT_DEEPENING_TIMEFRAMES = ("4h", "1h", "30m")


def _fetch_deepening_candles(symbol: str, tf: str, start_ts: Any, end_ts: Any) -> List[Any]:
    from src.adapters.binance_data import fetch_binance_ohlc_sync
    from src.adapters.deriv_data import fetch_deriv_ohlc_sync
    from src.adapters.yfinance_data import fetch_yfinance_ohlc_sync, is_yfinance_symbol

    sym_upper = symbol.upper()
    if sym_upper.endswith("USDT") or sym_upper.endswith("BTC"):
        candles = fetch_binance_ohlc_sync(symbol, tf)
    elif is_yfinance_symbol(symbol):
        candles = fetch_yfinance_ohlc_sync(symbol, tf)
    else:
        candles = fetch_deriv_ohlc_sync(symbol, tf)

    if start_ts and end_ts:
        candles = [c for c in candles if start_ts <= c.timestamp <= end_ts]
    return candles


def find_crossing_attempt(
    candles: List[Any],
    slice_start: int,
    slice_end: int,
    first_move_end: int,
    structural_level: Dict[str, Any],
    choch_zone: Optional[Dict[str, Any]],
    global_trend: str,
) -> Optional[Dict[str, Any]]:
    """Find the first crossing attempt after the first move.

    Step 1: scan forward from first_move_end to find the first candle
            where price crosses the BOS level.
    Step 2: scan backwards from that candle to find where the move started
            — the lowest low (uptrend) or highest high (downtrend) before
            the crossing.
    Step 3: verify the start is within or near the CHoCH zone.
    Step 4: return the crossing attempt dict.
    """
    bos_price = float(structural_level["price"])
    scan_end = min(slice_end, len(candles) - 1)

    # Step 1: find first candle that crosses BOS
    crossing_index = None
    for i in range(first_move_end + 1, scan_end + 1):
        if global_trend == "down":
            # retracement goes up — BOS is crossed when high >= bos_price
            if candles[i].high >= bos_price:
                crossing_index = i
                break
        else:
            # retracement goes down — BOS is crossed when low <= bos_price
            if candles[i].low <= bos_price:
                crossing_index = i
                break

    if crossing_index is None:
        return None

    # Record first BOS touch before scanning for the move extreme
    first_crossing_index = crossing_index

    # Step 1b: extend forward to find the extreme of the crossing move
    if global_trend == "down":
        # retracement goes up — find the highest high before two consecutive bearish candles
        extreme_index = crossing_index
        extreme_price = candles[crossing_index].high
        for i in range(crossing_index + 1, scan_end + 1):
            if candles[i].high > extreme_price:
                extreme_price = candles[i].high
                extreme_index = i
            else:
                # Require two consecutive bearish candles to confirm reversal
                if (i + 1 <= scan_end
                        and candles[i].low < candles[i - 1].low
                        and candles[i].high < candles[i - 1].high
                        and candles[i + 1].low < candles[i].low
                        and candles[i + 1].high < candles[i].high):
                    break
        crossing_index = extreme_index
        crossing_price = extreme_price
    else:
        # retracement goes down — find the lowest low before two consecutive bullish candles
        extreme_index = crossing_index
        extreme_price = candles[crossing_index].low
        for i in range(crossing_index + 1, scan_end + 1):
            if candles[i].low < extreme_price:
                extreme_price = candles[i].low
                extreme_index = i
            else:
                if (i + 1 <= scan_end
                        and candles[i].high > candles[i - 1].high
                        and candles[i].low > candles[i - 1].low
                        and candles[i + 1].high > candles[i].high
                        and candles[i + 1].low > candles[i].low):
                    break
        crossing_index = extreme_index
        crossing_price = extreme_price

    # Step 2: scan backwards from first_crossing_index (first BOS touch) to find move start
    # For uptrend retracement (going up): find the lowest low between
    # first_move_end and first_crossing_index
    # For downtrend retracement (going down): find the highest high
    move_start_index = first_move_end
    if global_trend == "down":
        # retracement going up — find lowest low
        lowest_price = float('inf')
        for i in range(first_move_end, first_crossing_index):
            if candles[i].low < lowest_price:
                lowest_price = candles[i].low
                move_start_index = i
    else:
        # retracement going down — find highest high
        highest_price = float('-inf')
        for i in range(first_move_end, first_crossing_index):
            if candles[i].high > highest_price:
                highest_price = candles[i].high
                move_start_index = i

    move_start_price = (candles[move_start_index].low
                        if global_trend == "down"
                        else candles[move_start_index].high)

    # Step 3: verify start is within or near CHoCH zone
    if choch_zone is not None:
        lower = float(choch_zone["lower_boundary"])
        upper = float(choch_zone["upper_boundary"])
        zone_width = max(upper - lower, 1.0)
        if global_trend == "down":
            in_zone = lower <= move_start_price <= upper
            near_zone = (lower - 2.0 * zone_width) <= move_start_price < lower
        else:
            in_zone = lower <= move_start_price <= upper
            near_zone = upper < move_start_price <= (upper + 2.0 * zone_width)
        if not (in_zone or near_zone):
            return None

    return {
        "start_index": move_start_index - slice_start,
        "end_index": crossing_index - slice_start,
        "start_price": move_start_price,
        "end_price": crossing_price,
        "global_start_index": move_start_index,
        "global_end_index": crossing_index,
        "choch_zone": choch_zone,
    }


def _walk_level(
    candles: List[Any],
    slice_start: int,
    slice_end: int,
    global_trend: str,
    filter_config: Dict[str, Any],
    rmt_filter_config: Dict[str, Any],
    current_depth: int,
    max_depth: int,
    deepening_timeframes: List[str],
    symbol: Optional[str] = None,
    known_first_move_end_index: Optional[int] = None,
    known_first_move_end_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Recursively build structural depth levels."""
    level: Dict[str, Any] = {
        "depth": current_depth,
        "slice_start": int(slice_start),
        "slice_end": int(slice_end),
        "rmt_result": None,
        "first_impulse": None,
        "first_impulse_global_start": None,
        "first_impulse_global_end": None,
        "internal_result": None,
        "internal_tf_used": "current",
        "internal_tf_slice_timestamps": None,
        "structural_level": None,
        "choch_zone": None,
        "crossing_attempt": None,
        "choch_mitigated": False,
        "termination_reason": "slice_too_small",
        "child": None,
    }

    if slice_start < 0 or slice_end < slice_start or slice_end >= len(candles):
        return level

    slice_candles = candles[slice_start : slice_end + 1]
    if len(slice_candles) < 10:
        return level

    first_move_start = slice_start

    if known_first_move_end_index is not None and known_first_move_end_price is not None:
        first_move_end = known_first_move_end_index
        first_move_end_price = known_first_move_end_price
    else:
        direction = "high" if global_trend == "down" else "low"
        candidates = _collect_candidates(candles, slice_start, direction, min_swing_candles=3)
        scored = _score_candidates(candles, candidates, direction)

        total_range = max(c.high for c in slice_candles) - min(c.low for c in slice_candles)
        min_distance = filter_config.get("min_impulse_parent_ratio", 0.15) * total_range
        anchor_price = float(candles[slice_start].close)

        qualified = [
            c for c in scored
            if abs(float(c["price"]) - anchor_price) >= min_distance
        ]
        if not qualified:
            level["termination_reason"] = "no_structural_level"
            return level

        if global_trend == "down":
            best = max(qualified, key=lambda c: (c.get("score", 0.0), c["price"], -c["index"]))
        else:
            best = max(qualified, key=lambda c: (c.get("score", 0.0), -c["price"], -c["index"]))

        first_move_end = int(best["index"])
        first_move_end_price = float(best["price"])

    structural_level = {
        "price": first_move_end_price,
        "source_leg_end_index": first_move_end,
    }
    level["structural_level"] = structural_level

    level["first_impulse"] = {
        "type": "impulse",
        "confirmed": True,
        "start_price": float(candles[slice_start].close),
        "end_price": first_move_end_price,
        "start_index": slice_start,
        "end_index": first_move_end,
    }
    level["first_impulse_global_start"] = first_move_start
    level["first_impulse_global_end"] = first_move_end

    first_move_candles = candles[first_move_start : first_move_end + 1]

    _legs_for_internal = [{
        "type": "impulse",
        "confirmed": True,
        "start_price": float(first_move_candles[0].close),
        "end_price": float(first_move_candles[-1].close),
        "start_index": 0,
        "end_index": len(first_move_candles) - 1,
        "end_timestamp": first_move_candles[-1].timestamp,
        "start_timestamp": first_move_candles[0].timestamp,
        "slope": None,
        "internal_structure": None,
    }]
    compute_internal_structure(
        first_move_candles,
        _legs_for_internal,
        trend_confirmation_pct=0.005,
        **filter_config
    )
    internal_result = _legs_for_internal[0].get("internal_structure")
    internal_tf_used = "current"
    internal_tf_slice_timestamps = None

    confirmed_internal = [
        leg for leg in (internal_result or {}).get("legs", [])
        if leg.get("confirmed")
    ]

    should_attempt_fallback = (
        symbol is not None
        and len(confirmed_internal) < 3
    )

    if should_attempt_fallback:
        impulse_start_ts = candles[first_move_start].timestamp
        impulse_end_ts = candles[first_move_end].timestamp

        for tf_key in deepening_timeframes:
            try:
                tf_slice = _fetch_deepening_candles(
                    symbol, tf_key, impulse_start_ts, impulse_end_ts
                )
                if len(tf_slice) < 100:
                    continue

                _legs_for_tf = [{
                    "type": "impulse",
                    "confirmed": True,
                    "start_price": float(tf_slice[0].close),
                    "end_price": float(tf_slice[-1].close),
                    "start_index": 0,
                    "end_index": len(tf_slice) - 1,
                    "end_timestamp": tf_slice[-1].timestamp,
                    "start_timestamp": tf_slice[0].timestamp,
                    "slope": None,
                    "internal_structure": None,
                }]
                compute_internal_structure(
                    tf_slice,
                    _legs_for_tf,
                    trend_confirmation_pct=0.005,
                    **filter_config
                )
                tf_internal = _legs_for_tf[0].get("internal_structure")
                tf_outer_confirmed = [
                    leg for leg in (tf_internal or {}).get("legs", [])
                    if leg.get("confirmed")
                ]
                tf_inner_confirmed = []
                for tf_leg in tf_outer_confirmed:
                    if tf_leg.get("internal_structure"):
                        tf_inner_confirmed += [
                            internal_leg
                            for internal_leg in tf_leg["internal_structure"].get("legs", [])
                            if internal_leg.get("confirmed")
                        ]
                total_tf_confirmed = len(tf_outer_confirmed) + len(tf_inner_confirmed)
                if total_tf_confirmed >= 3:
                    internal_result = tf_internal
                    first_move_candles = tf_slice
                    internal_tf_used = tf_key
                    internal_tf_slice_timestamps = [candle.timestamp for candle in tf_slice]
                    break
            except Exception:
                continue

    if internal_result is not None:
        compute_internal_structure(
            first_move_candles,
            internal_result["legs"],
            trend_confirmation_pct=0.005,
            **filter_config,
        )
    level["first_move_candles"] = first_move_candles
    level["internal_result"] = internal_result
    level["internal_tf_used"] = internal_tf_used
    level["internal_tf_slice_timestamps"] = internal_tf_slice_timestamps

    if internal_result is not None and internal_result.get("trend") != "range":
        choch = get_active_choch_zone(
            internal_result["legs"],
            internal_result["trend"],
            first_move_candles,
        )
        choch_zone = choch["choch_zone"] if choch else None

        # If outer int_result has only 1 confirmed impulse, look inside leg[0]'s internal_structure
        if choch_zone is None:
            first_leg = next(
                (
                    l for l in internal_result["legs"]
                    if l.get("type") == "impulse" and l.get("confirmed")
                    and l.get("internal_structure") is not None
                ),
                None,
            )
            if first_leg is not None:
                inner = first_leg["internal_structure"]
                inner_start = int(first_leg["start_index"])
                inner_end = int(first_leg["end_index"])
                inner_candles = first_move_candles[inner_start : inner_end + 1]
                inner_choch = get_active_choch_zone(
                    inner["legs"],
                    inner["trend"],
                    inner_candles,
                )
                choch_zone = inner_choch["choch_zone"] if inner_choch else None

        # Final fallback: last confirmed retracement range
        if choch_zone is None:
            confirmed_rets = [
                l for l in internal_result.get("legs", [])
                if l.get("type") == "retracement" and l.get("confirmed")
                and l.get("start_price") is not None and l.get("end_price") is not None
            ]
            if confirmed_rets:
                last_ret = confirmed_rets[-1]
                lower = min(float(last_ret["start_price"]), float(last_ret["end_price"]))
                upper = max(float(last_ret["start_price"]), float(last_ret["end_price"]))
                choch_zone = {
                    "lower_boundary": lower,
                    "upper_boundary": upper,
                    "zone_width_pct": 0.0,
                    "zone_midpoint": (lower + upper) / 2,
                    "trend_direction": internal_result.get("trend", "up"),
                    "source_impulse_start_index": 0,
                    "source_impulse_end_index": 0,
                    "prior_impulse_end_index": 0,
                }
        level["choch_zone"] = choch_zone
    else:
        choch_zone = None
        level["choch_zone"] = None

    level["rmt_result"] = None
    crossing_attempt = find_crossing_attempt(
        candles=candles,
        slice_start=slice_start,
        slice_end=slice_end,
        first_move_end=first_move_end,
        structural_level=structural_level,
        choch_zone=choch_zone,
        global_trend=global_trend,
    )

    level["crossing_attempt"] = crossing_attempt
    level["choch_mitigated"] = crossing_attempt is not None

    if crossing_attempt is None:
        level["termination_reason"] = "no_crossing_attempt"
        return level

    if current_depth >= max_depth:
        level["termination_reason"] = "max_depth_reached"
        return level

    child = _walk_level(
        candles,
        crossing_attempt["global_start_index"],
        slice_end,
        global_trend,
        filter_config,
        rmt_filter_config,
        current_depth + 1,
        max_depth,
        deepening_timeframes,
        symbol=symbol,
        known_first_move_end_index=crossing_attempt["global_end_index"],
        known_first_move_end_price=crossing_attempt["end_price"],
    )
    level["child"] = child
    level["termination_reason"] = child["termination_reason"]
    return level


def walk_structure(
    candles: List[Any],
    result: Dict[str, Any],
    filter_config: Dict[str, Any],
    max_depth: int = 4,
    rmt_filter_config: Optional[Dict[str, Any]] = None,
    symbol: Optional[str] = None,
    deepening_timeframes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Public entry point for recursive structural depth analysis."""
    global_trend = result.get("trend", "range")

    def _not_walkable(reason: str) -> Dict[str, Any]:
        return {
            "walkable": False,
            "reason": reason,
            "global_trend": global_trend,
            "levels": [],
            "total_mitigation_count": 0,
            "max_depth_reached": 0,
            "deepest_termination_reason": reason,
            "active_level": 0,
            "waiting_for": "Waiting for price to reach global CHoCH zone",
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

    retracement_leg = confirmed_retracements[-1]
    slice_start = int(retracement_leg["start_index"])
    slice_end = (
        int(retracement_leg["end_index"])
        if retracement_leg.get("end_index") is not None
        else len(candles) - 1
    )

    effective_rmt_config = rmt_filter_config if rmt_filter_config is not None else RMT_DEFAULT_FILTER_CONFIG
    dfs = (
        list(deepening_timeframes)
        if deepening_timeframes is not None
        else list(_DEFAULT_DEEPENING_TIMEFRAMES)
    )

    root = _walk_level(
        candles,
        slice_start,
        slice_end,
        global_trend,
        filter_config,
        effective_rmt_config,
        current_depth=1,
        max_depth=max_depth,
        deepening_timeframes=dfs,
        symbol=symbol,
    )

    levels: List[Dict[str, Any]] = []
    node = root
    while node is not None:
        levels.append(node)
        node = node.get("child")

    total_mitigation_count = sum(1 for level in levels if level.get("choch_mitigated") is True)
    max_depth_reached = max((level["depth"] for level in levels), default=0)
    deepest = levels[-1] if levels else {
        "depth": 0,
        "termination_reason": "unknown",
        "structural_level": None,
    }
    deepest_reason = deepest.get("termination_reason", "unknown")

    active_level = 0
    for level in levels:
        if level.get("crossing_attempt") is not None:
            active_level = max(active_level, int(level["depth"]))

    if deepest_reason == "no_crossing_attempt":
        waiting_for = "Price has not yet reached the CHoCH zone — monitoring"
    elif deepest_reason == "no_choch_zone":
        waiting_for = f"Waiting for price to reach depth {deepest['depth']} CHoCH zone"
    elif deepest_reason == "no_structural_level":
        waiting_for = (
            f"Depth {deepest['depth']} CHoCH zone active — watching for entry impulse"
        )
    elif deepest_reason == "max_depth_reached":
        waiting_for = (
            f"All depth levels confirmed — watching for entry signal at depth {deepest['depth']} CHoCH zone"
        )
    elif deepest_reason == "slice_too_small":
        bos = deepest.get("structural_level")
        bos_price = f"{float(bos['price']):.2f}" if bos and bos.get("price") is not None else "unknown"
        waiting_for = f"Price inside CHoCH zone — watching for BOS break at {bos_price}"
    else:
        waiting_for = "Waiting for price to reach global CHoCH zone"

    return {
        "walkable": True,
        "reason": None,
        "global_trend": global_trend,
        "levels": levels,
        "total_mitigation_count": total_mitigation_count,
        "max_depth_reached": max_depth_reached,
        "deepest_termination_reason": deepest_reason,
        "active_level": active_level,
        "waiting_for": waiting_for,
        "stars_aligned": False,
    }


def serialize_state_report(state_report: Dict[str, Any]) -> Dict[str, Any]:
    """Strip non-serializable objects from walk_structure output.

    Removes first_move_candles, internal_result, and rmt_result from each
    level. Converts datetime objects to ISO format strings. Returns a clean
    dict safe for json.dumps() and database storage.

    The Orchestrator must always call this before writing to the database.
    The raw state_report with Candle objects stays in memory for notebook use only.
    """
    import copy
    from datetime import datetime

    # Fields to remove from each depth level before serialization.
    # These contain Candle objects or large intermediate results
    # not needed by the Orchestrator.
    LEVEL_FIELDS_TO_STRIP = {
        "first_move_candles",  # list of Candle objects
        "internal_result",     # large intermediate identify_trend result
        "rmt_result",          # large intermediate identify_trend result
        "internal_tf_slice_timestamps",  # list of datetime objects
    }

    def _strip_level(lvl: Dict[str, Any]) -> None:
        """Recursively strip non-serializable fields from a level and its child chain."""
        for field in LEVEL_FIELDS_TO_STRIP:
            lvl.pop(field, None)
        child = lvl.get("child")
        if child is not None:
            _strip_level(child)

    def _convert_value(v: Any) -> Any:
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, dict):
            return {k: _convert_value(val) for k, val in v.items()}
        if isinstance(v, list):
            return [_convert_value(item) for item in v]
        return v

    serialized = copy.deepcopy(state_report)

    # Pass 1: strip non-serializable fields from all levels and their child chains.
    # Must run before _convert_value so the child dicts are free of Candle objects
    # before _convert_value recurses into them.
    for level in serialized.get("levels", []):
        _strip_level(level)

    # Pass 2: convert any remaining datetime objects recursively
    for level in serialized.get("levels", []):
        for key in list(level.keys()):
            level[key] = _convert_value(level[key])

    # Convert top-level fields
    for key in list(serialized.keys()):
        if key != "levels":
            serialized[key] = _convert_value(serialized[key])

    levels = serialized.get("levels", [])
    global_choch_zone = None
    if levels:
        first_level = levels[0]
        first_level_choch_zone = first_level.get("choch_zone")
        if isinstance(first_level_choch_zone, dict):
            lower_boundary = first_level_choch_zone.get("lower_boundary")
            upper_boundary = first_level_choch_zone.get("upper_boundary")
            if lower_boundary is not None and upper_boundary is not None:
                global_choch_zone = {
                    "lower_boundary": float(lower_boundary),
                    "upper_boundary": float(upper_boundary),
                }

    serialized["global_choch_zone"] = global_choch_zone

    return serialized
