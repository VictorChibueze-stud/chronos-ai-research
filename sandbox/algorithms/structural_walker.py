"""Recursive structural depth walker for Ikenga.

Depth model:
- A new depth level is created only when a trend that started from the prior
  depth's CHoCH zone crosses that prior depth's BOS (structural level).
- That crossing trend slice becomes the next depth input.

Pure stateless module. No side effects. No file I/O.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from choch_zone import get_active_choch_zone
from structure_levels import collapse_false_break_impulses
from trend_id import (
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

_DEFAULT_DEEPENING_TIMEFRAMES = ("4h", "1h", "30m", "15m", "5m")
_DEFAULT_DEEPENING_SELECTION_MODE = "first_valid"


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


def _as_utc_timestamp(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None


def _clip_candles_to_range(
    candles: List[Any],
    start_ts: Any,
    end_ts: Any,
) -> List[Any]:
    start_dt = _as_utc_timestamp(start_ts)
    end_dt = _as_utc_timestamp(end_ts)
    if start_dt is None or end_dt is None:
        return []
    return [
        candle for candle in candles
        if start_dt <= _as_utc_timestamp(candle.timestamp) <= end_dt
    ]


def _nearest_global_index_from_timestamp(candles: List[Any], target_ts: Any) -> Optional[int]:
    target_dt = _as_utc_timestamp(target_ts)
    if target_dt is None or not candles:
        return None
    best_index = None
    best_distance = None
    for index, candle in enumerate(candles):
        candle_dt = _as_utc_timestamp(candle.timestamp)
        if candle_dt is None:
            continue
        distance = abs((candle_dt - target_dt).total_seconds())
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_index = index
    return best_index


def _first_impulse_duration_seconds(impulse: Optional[Dict[str, Any]]) -> float:
    if not impulse:
        return -1.0
    start_dt = _as_utc_timestamp(impulse.get("start_timestamp"))
    end_dt = _as_utc_timestamp(impulse.get("end_timestamp"))
    if start_dt is None or end_dt is None:
        return -1.0
    return max(0.0, (end_dt - start_dt).total_seconds())


def _build_internal_candidate(
    slice_candles: List[Any],
    tf_label: str,
    order: int,
    filter_config: Dict[str, Any],
    walker_trend_confirmation_pct: float,
    apply_false_break_cleaner: bool,
    false_break_retrace_ratio: float,
    false_break_max_iterations: int,
) -> Optional[Dict[str, Any]]:
    if len(slice_candles) < 10:
        return None

    internal_result = identify_trend(
        slice_candles,
        trend_confirmation_pct=walker_trend_confirmation_pct,
        **filter_config,
    )
    if internal_result.get("trend") not in {"up", "down"}:
        return {
            "tf": tf_label,
            "internal_result": None,
            "slice_candles": slice_candles,
            "slice_timestamps": [candle.timestamp for candle in slice_candles],
            "total_confirmed": 0,
            "first_impulse_duration_seconds": -1.0,
            "has_anchored_first_impulse": 0,
            "order": order,
        }

    compute_internal_structure(
        slice_candles,
        internal_result["legs"],
        trend_confirmation_pct=walker_trend_confirmation_pct,
        **filter_config,
    )

    if apply_false_break_cleaner:
        cleanup = collapse_false_break_impulses(
            internal_result["legs"],
            internal_result["trend"],
            false_break_retrace_ratio=false_break_retrace_ratio,
            max_iterations=false_break_max_iterations,
        )
        internal_result["legs"] = cleanup.get("legs", internal_result["legs"])
        compute_internal_structure(
            slice_candles,
            internal_result["legs"],
            trend_confirmation_pct=walker_trend_confirmation_pct,
            **filter_config,
        )

    first_impulse = _first_confirmed_impulse(internal_result)
    start_index = first_impulse.get("start_index") if first_impulse else None
    return {
        "tf": tf_label,
        "internal_result": internal_result,
        "slice_candles": slice_candles,
        "slice_timestamps": [candle.timestamp for candle in slice_candles],
        "total_confirmed": _confirmed_leg_count_for_deepening(internal_result),
        "first_impulse_duration_seconds": _first_impulse_duration_seconds(first_impulse),
        "has_anchored_first_impulse": 1 if isinstance(start_index, int) and start_index == 0 else 0,
        "order": order,
    }


def _select_internal_structure_for_range(
    candles: List[Any],
    range_start_ts: Any,
    range_end_ts: Any,
    filter_config: Dict[str, Any],
    walker_trend_confirmation_pct: float,
    symbol: Optional[str],
    deepening_timeframes: List[str],
    deepening_selection_mode: str,
    apply_false_break_cleaner: bool,
    false_break_retrace_ratio: float,
    false_break_max_iterations: int,
) -> Optional[Dict[str, Any]]:
    base_slice = _clip_candles_to_range(candles, range_start_ts, range_end_ts)
    candidates: List[Dict[str, Any]] = []
    current_candidate = _build_internal_candidate(
        base_slice,
        "current",
        0,
        filter_config,
        walker_trend_confirmation_pct,
        apply_false_break_cleaner,
        false_break_retrace_ratio,
        false_break_max_iterations,
    )
    if current_candidate is not None:
        candidates.append(current_candidate)

    if symbol is not None:
        for order, tf_key in enumerate(deepening_timeframes, start=1):
            try:
                tf_slice = _fetch_deepening_candles(symbol, tf_key, range_start_ts, range_end_ts)
            except Exception:
                continue
            tf_candidate = _build_internal_candidate(
                tf_slice,
                tf_key,
                order,
                filter_config,
                walker_trend_confirmation_pct,
                apply_false_break_cleaner,
                false_break_retrace_ratio,
                false_break_max_iterations,
            )
            if tf_candidate is not None:
                candidates.append(tf_candidate)

    return _pick_deepening_candidate(candidates, deepening_selection_mode)


def _confirmed_leg_count_for_deepening(internal_result: Optional[Dict[str, Any]]) -> int:
    if not internal_result:
        return 0
    outer = [
        leg for leg in internal_result.get("legs", [])
        if leg.get("confirmed")
    ]
    inner_count = 0
    for leg in outer:
        nested = leg.get("internal_structure") or {}
        inner_count += sum(1 for il in nested.get("legs", []) if il.get("confirmed"))
    return len(outer) + inner_count


def _first_confirmed_impulse(internal_result: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not internal_result:
        return None
    impulses = [
        leg for leg in internal_result.get("legs", [])
        if leg.get("type") == "impulse" and leg.get("confirmed")
    ]
    if not impulses:
        return None

    anchored = [
        leg for leg in impulses
        if isinstance(leg.get("start_index"), int) and leg.get("start_index") == 0
    ]
    source = anchored if anchored else impulses
    return min(
        source,
        key=lambda leg: (
            int(leg.get("start_index") or 0),
            int(leg.get("end_index") or 0),
        ),
    )


def _pick_deepening_candidate(
    candidates: List[Dict[str, Any]],
    selection_mode: str,
) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None

    mode = (selection_mode or _DEFAULT_DEEPENING_SELECTION_MODE).strip().lower()
    if mode == "first_valid":
        for candidate in candidates:
            if int(candidate.get("total_confirmed", 0)) >= 3:
                return candidate
        return candidates[0]

    ranked = [
        candidate
        for candidate in candidates
        if int(candidate.get("total_confirmed", 0)) > 0
    ]
    if not ranked:
        return candidates[0]

    if mode == "most_legs":
        return max(
            ranked,
            key=lambda candidate: (
                int(candidate.get("total_confirmed", 0)),
                float(candidate.get("first_impulse_duration_seconds", -1.0)),
                -int(candidate.get("order", 0)),
            ),
        )

    if mode == "least_legs":
        return min(
            ranked,
            key=lambda candidate: (
                int(candidate.get("total_confirmed", 0)),
                -float(candidate.get("first_impulse_duration_seconds", -1.0)),
                int(candidate.get("order", 0)),
            ),
        )

    if mode == "longest_first_impulse":
        return max(
            ranked,
            key=lambda candidate: (
                int(candidate.get("has_anchored_first_impulse", 0)),
                float(candidate.get("first_impulse_duration_seconds", -1.0)),
                int(candidate.get("total_confirmed", 0)),
                -int(candidate.get("order", 0)),
            ),
        )

    return _pick_deepening_candidate(candidates, "first_valid")


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
    walker_trend_confirmation_pct: float,
    rmt_filter_config: Dict[str, Any],
    current_depth: int,
    max_depth: int,
    deepening_timeframes: List[str],
    deepening_selection_mode: str,
    apply_false_break_cleaner: bool,
    false_break_retrace_ratio: float,
    false_break_max_iterations: int,
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
        "internal_tf_selection_mode": deepening_selection_mode,
        "seed_tf_used": "current",
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

    if current_depth == 1 and known_first_move_end_index is None and known_first_move_end_price is None:
        retracement_start_ts = candles[slice_start].timestamp
        retracement_end_ts = candles[slice_end].timestamp
        seed_candidate = _select_internal_structure_for_range(
            candles,
            retracement_start_ts,
            retracement_end_ts,
            filter_config,
            walker_trend_confirmation_pct,
            symbol,
            deepening_timeframes,
            deepening_selection_mode,
            apply_false_break_cleaner,
            false_break_retrace_ratio,
            false_break_max_iterations,
        )
        seed_internal_result = seed_candidate.get("internal_result") if seed_candidate else None
        if seed_internal_result is None:
            level["termination_reason"] = "no_structural_level"
            return level

        seed_first_impulse = _first_confirmed_impulse(seed_internal_result)
        if seed_first_impulse is None:
            level["termination_reason"] = "no_structural_level"
            return level

        global_start_index = _nearest_global_index_from_timestamp(
            candles,
            seed_first_impulse.get("start_timestamp"),
        )
        global_end_index = _nearest_global_index_from_timestamp(
            candles,
            seed_first_impulse.get("end_timestamp"),
        )
        if global_start_index is None or global_end_index is None or global_end_index < global_start_index:
            level["termination_reason"] = "no_structural_level"
            return level

        first_move_start = global_start_index
        first_move_end = global_end_index
        first_move_end_price = float(seed_first_impulse["end_price"])
        level["seed_tf_used"] = seed_candidate.get("tf", "current") if seed_candidate else "current"

        structural_level = {
            "price": first_move_end_price,
            "source_leg_end_index": first_move_end,
        }
        level["structural_level"] = structural_level
        level["first_impulse"] = {
            "type": "impulse",
            "confirmed": True,
            "start_price": float(seed_first_impulse["start_price"]),
            "end_price": float(seed_first_impulse["end_price"]),
            "start_index": first_move_start,
            "end_index": first_move_end,
            "start_timestamp": seed_first_impulse.get("start_timestamp"),
            "end_timestamp": seed_first_impulse.get("end_timestamp"),
        }
        level["first_impulse_global_start"] = first_move_start
        level["first_impulse_global_end"] = first_move_end

        d1_candidate = _select_internal_structure_for_range(
            candles,
            seed_first_impulse.get("start_timestamp"),
            seed_first_impulse.get("end_timestamp"),
            filter_config,
            walker_trend_confirmation_pct,
            symbol,
            deepening_timeframes,
            deepening_selection_mode,
            apply_false_break_cleaner,
            false_break_retrace_ratio,
            false_break_max_iterations,
        )
        internal_result = d1_candidate.get("internal_result") if d1_candidate else None
        first_move_candles = d1_candidate.get("slice_candles", candles[first_move_start : first_move_end + 1]) if d1_candidate else candles[first_move_start : first_move_end + 1]
        internal_tf_used = d1_candidate.get("tf", "current") if d1_candidate else "current"
        internal_tf_slice_timestamps = d1_candidate.get("slice_timestamps") if d1_candidate else None
    elif known_first_move_end_index is not None and known_first_move_end_price is not None:
        first_move_end = known_first_move_end_index
        first_move_end_price = known_first_move_end_price

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
            "start_timestamp": candles[slice_start].timestamp,
            "end_timestamp": candles[first_move_end].timestamp,
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
            trend_confirmation_pct=walker_trend_confirmation_pct,
            **filter_config
        )
        internal_result = _legs_for_internal[0].get("internal_structure")
        internal_tf_used = "current"
        internal_tf_slice_timestamps = None
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
            trend_confirmation_pct=walker_trend_confirmation_pct,
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
        current_depth > 1
        and symbol is not None
        and (
            len(confirmed_internal) < 3
            or deepening_selection_mode != _DEFAULT_DEEPENING_SELECTION_MODE
        )
    )

    if should_attempt_fallback:
        impulse_start_ts = candles[first_move_start].timestamp
        impulse_end_ts = candles[first_move_end].timestamp

        candidate_structures: List[Dict[str, Any]] = []
        current_first_impulse = _first_confirmed_impulse(internal_result)
        current_first_impulse_duration_seconds = -1.0
        current_has_anchored_first_impulse = 0
        if current_first_impulse is not None:
            si = int(current_first_impulse.get("start_index") or 0)
            current_first_impulse_duration_seconds = _first_impulse_duration_seconds(current_first_impulse)
            current_has_anchored_first_impulse = 1 if si == 0 else 0
        candidate_structures.append({
            "tf": "current",
            "internal_result": internal_result,
            "slice_candles": first_move_candles,
            "slice_timestamps": None,
            "total_confirmed": _confirmed_leg_count_for_deepening(internal_result),
            "first_impulse_duration_seconds": current_first_impulse_duration_seconds,
            "has_anchored_first_impulse": current_has_anchored_first_impulse,
            "order": 0,
        })

        for idx, tf_key in enumerate(deepening_timeframes, start=1):
            try:
                tf_slice = _fetch_deepening_candles(
                    symbol, tf_key, impulse_start_ts, impulse_end_ts
                )
                if len(tf_slice) < 10:
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
                    trend_confirmation_pct=walker_trend_confirmation_pct,
                    **filter_config
                )
                tf_internal = _legs_for_tf[0].get("internal_structure")
                if tf_internal is not None and apply_false_break_cleaner and tf_internal.get("trend") in {"up", "down"}:
                    cleanup = collapse_false_break_impulses(
                        tf_internal["legs"],
                        tf_internal["trend"],
                        false_break_retrace_ratio=false_break_retrace_ratio,
                        max_iterations=false_break_max_iterations,
                    )
                    tf_internal["legs"] = cleanup.get("legs", tf_internal["legs"])
                    compute_internal_structure(
                        tf_slice,
                        tf_internal["legs"],
                        trend_confirmation_pct=walker_trend_confirmation_pct,
                        **filter_config
                    )
                tf_first_impulse = _first_confirmed_impulse(tf_internal)
                tf_first_impulse_duration_seconds = -1.0
                tf_has_anchored_first_impulse = 0
                if tf_first_impulse is not None:
                    si = int(tf_first_impulse.get("start_index") or 0)
                    tf_first_impulse_duration_seconds = _first_impulse_duration_seconds(tf_first_impulse)
                    tf_has_anchored_first_impulse = 1 if si == 0 else 0

                candidate_structures.append({
                    "tf": tf_key,
                    "internal_result": tf_internal,
                    "slice_candles": tf_slice,
                    "slice_timestamps": [candle.timestamp for candle in tf_slice],
                    "total_confirmed": _confirmed_leg_count_for_deepening(tf_internal),
                    "first_impulse_duration_seconds": tf_first_impulse_duration_seconds,
                    "has_anchored_first_impulse": tf_has_anchored_first_impulse,
                    "order": idx,
                })
            except Exception:
                continue

        picked = _pick_deepening_candidate(candidate_structures, deepening_selection_mode)
        if picked is not None:
            internal_result = picked.get("internal_result")
            first_move_candles = picked.get("slice_candles", first_move_candles)
            internal_tf_used = picked.get("tf", "current")
            internal_tf_slice_timestamps = picked.get("slice_timestamps")

    if internal_result is not None:
        compute_internal_structure(
            first_move_candles,
            internal_result["legs"],
            trend_confirmation_pct=walker_trend_confirmation_pct,
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
                    "source": "internal_retracement_fallback",
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
        walker_trend_confirmation_pct,
        rmt_filter_config,
        current_depth + 1,
        max_depth,
        deepening_timeframes,
        deepening_selection_mode,
        apply_false_break_cleaner,
        false_break_retrace_ratio,
        false_break_max_iterations,
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
    walker_trend_confirmation_pct: float = 0.005,
    rmt_filter_config: Optional[Dict[str, Any]] = None,
    symbol: Optional[str] = None,
    deepening_timeframes: Optional[List[str]] = None,
    deepening_selection_mode: str = _DEFAULT_DEEPENING_SELECTION_MODE,
    apply_false_break_cleaner: bool = False,
    false_break_retrace_ratio: float = 0.60,
    false_break_max_iterations: int = 20,
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
    effective_filter_config = dict(filter_config or {})
    # walker_trend_confirmation_pct is passed explicitly to avoid duplicate kwargs
    effective_filter_config.pop("trend_confirmation_pct", None)
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
        effective_filter_config,
        walker_trend_confirmation_pct,
        effective_rmt_config,
        current_depth=1,
        max_depth=max_depth,
        deepening_timeframes=dfs,
        deepening_selection_mode=deepening_selection_mode,
        apply_false_break_cleaner=apply_false_break_cleaner,
        false_break_retrace_ratio=false_break_retrace_ratio,
        false_break_max_iterations=false_break_max_iterations,
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
