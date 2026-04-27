from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from src.analysis.override_utils import assign_boundary_roles, snap_to_wick_extreme


def _ov_field(override: Any, name: str, default: Any = None) -> Any:
    if override is None:
        return default
    if isinstance(override, dict):
        return override.get(name, default)
    return getattr(override, name, default)


def _candle_field(candle: Any, field_name: str) -> Any:
    if isinstance(candle, dict):
        return candle.get(field_name)
    return getattr(candle, field_name, None)


def _ensure_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _filter_candles_by_window(
    candles: list,
    start_ts: Optional[datetime],
    end_ts: Optional[datetime],
) -> list:
    if not candles:
        return []

    if start_ts is None and end_ts is None:
        return list(candles)

    start_u = _ensure_utc(start_ts) if start_ts is not None else None
    end_u = _ensure_utc(end_ts) if end_ts is not None else None

    filtered = []
    for c in candles:
        ts = _candle_field(c, "timestamp")
        if ts is None:
            continue
        ts_u = _ensure_utc(ts)
        if start_u is not None and ts_u < start_u:
            continue
        if end_u is not None and ts_u > end_u:
            continue
        filtered.append(c)
    return filtered


def _find_extreme_candle(candles: list, trend_direction: str) -> tuple[int, Any, float]:
    trend = trend_direction.lower().strip()
    if trend == "down":
        idx, candle = max(
            enumerate(candles),
            key=lambda item: float(_candle_field(item[1], "high")),
        )
        return idx, candle, float(_candle_field(candle, "high"))

    idx, candle = min(
        enumerate(candles),
        key=lambda item: float(_candle_field(item[1], "low")),
    )
    return idx, candle, float(_candle_field(candle, "low"))


def _derive_current_impulse(
    candles: list,
    start_index: int,
    trend_direction: str,
) -> tuple[Optional[int], Optional[float], bool]:
    if start_index >= len(candles):
        return None, None, False

    subset = candles[start_index:]
    if not subset:
        return None, None, False

    trend = trend_direction.lower().strip()
    if trend == "down":
        rel_idx, c = min(
            enumerate(subset),
            key=lambda item: float(_candle_field(item[1], "low")),
        )
        end_price = float(_candle_field(c, "low"))
    else:
        rel_idx, c = max(
            enumerate(subset),
            key=lambda item: float(_candle_field(item[1], "high")),
        )
        end_price = float(_candle_field(c, "high"))

    end_index = start_index + rel_idx
    confirmed = end_index > start_index
    return end_index if confirmed else None, end_price if confirmed else None, confirmed


def _build_zone_from_boundaries(
    impulse_end: dict,
    retracement_end: dict,
    trend_direction: str,
) -> dict:
    lower = min(float(impulse_end["snapped_price"]), float(retracement_end["snapped_price"]))
    upper = max(float(impulse_end["snapped_price"]), float(retracement_end["snapped_price"]))
    midpoint = (lower + upper) / 2.0
    zone_width_pct = round((upper - lower) / lower * 100, 2) if lower != 0 else 0.0
    return {
        "lower_boundary": lower,
        "upper_boundary": upper,
        "zone_width_pct": zone_width_pct,
        "zone_midpoint": midpoint,
        "trend_direction": trend_direction,
        "source_impulse_start_index": int(retracement_end["candle_index"]),
        "source_impulse_end_index": int(retracement_end["candle_index"]),
        "prior_impulse_end_index": int(impulse_end["candle_index"]),
    }


def _resolve_boundaries(
    override: Any,
    candles: list,
    trend_direction: str,
    search_radius: int,
) -> tuple[dict, dict] | tuple[None, None]:
    approx_price_a = _ov_field(override, "approx_price_a")
    approx_ts_a = _ov_field(override, "approx_timestamp_a")
    approx_price_b = _ov_field(override, "approx_price_b")
    approx_ts_b = _ov_field(override, "approx_timestamp_b")

    if approx_price_a is None or approx_ts_a is None or approx_price_b is None or approx_ts_b is None:
        return None, None

    role_prices = assign_boundary_roles(float(approx_price_a), float(approx_price_b), trend_direction)

    a_matches_impulse = float(approx_price_a) == float(role_prices["impulse_end_price"])
    if float(approx_price_a) == float(approx_price_b):
        a_matches_impulse = True

    if a_matches_impulse:
        impulse_input = (float(approx_price_a), _ensure_utc(approx_ts_a))
        retrace_input = (float(approx_price_b), _ensure_utc(approx_ts_b))
    else:
        impulse_input = (float(approx_price_b), _ensure_utc(approx_ts_b))
        retrace_input = (float(approx_price_a), _ensure_utc(approx_ts_a))

    snapped_impulse = snap_to_wick_extreme(
        approx_price=impulse_input[0],
        approx_timestamp=impulse_input[1],
        candles=candles,
        trend_direction=trend_direction,
        boundary_role="impulse_end",
        search_radius=search_radius,
    )
    snapped_retracement = snap_to_wick_extreme(
        approx_price=retrace_input[0],
        approx_timestamp=retrace_input[1],
        candles=candles,
        trend_direction=trend_direction,
        boundary_role="retracement_end",
        search_radius=search_radius,
    )

    if snapped_impulse is None or snapped_retracement is None:
        return None, None

    return snapped_impulse, snapped_retracement


def _build_override_trend_result(
    candles: list,
    trend_direction: str,
    snapped_impulse: dict,
    snapped_retracement: dict,
) -> dict:
    if not candles:
        return {
            "trend": "range",
            "trend_start": None,
            "legs": [],
            "current_phase": "unknown",
        }

    trend = trend_direction.lower().strip()
    start_idx, start_candle, start_price = _find_extreme_candle(candles, trend)

    leg1 = {
        "type": "impulse",
        "start_price": float(start_price),
        "start_index": int(start_idx),
        "start_timestamp": _ensure_utc(_candle_field(start_candle, "timestamp")),
        "end_price": float(snapped_impulse["snapped_price"]),
        "end_index": int(snapped_impulse["candle_index"]),
        "end_timestamp": _ensure_utc(snapped_impulse["snapped_timestamp"]),
        "confirmed": True,
        "slope": None,
    }

    leg2 = {
        "type": "retracement",
        "start_price": float(snapped_impulse["snapped_price"]),
        "start_index": int(snapped_impulse["candle_index"]),
        "start_timestamp": _ensure_utc(snapped_impulse["snapped_timestamp"]),
        "end_price": float(snapped_retracement["snapped_price"]),
        "end_index": int(snapped_retracement["candle_index"]),
        "end_timestamp": _ensure_utc(snapped_retracement["snapped_timestamp"]),
        "confirmed": True,
        "slope": None,
    }

    leg3_end_index, leg3_end_price, leg3_confirmed = _derive_current_impulse(
        candles,
        int(snapped_retracement["candle_index"]),
        trend,
    )

    leg3 = {
        "type": "impulse",
        "start_price": float(snapped_retracement["snapped_price"]),
        "start_index": int(snapped_retracement["candle_index"]),
        "start_timestamp": _ensure_utc(snapped_retracement["snapped_timestamp"]),
        "end_price": float(leg3_end_price) if leg3_confirmed and leg3_end_price is not None else None,
        "end_index": int(leg3_end_index) if leg3_confirmed and leg3_end_index is not None else None,
        "end_timestamp": _ensure_utc(_candle_field(candles[leg3_end_index], "timestamp"))
        if leg3_confirmed and leg3_end_index is not None
        else None,
        "confirmed": bool(leg3_confirmed),
        "slope": None,
    }

    legs = [leg1, leg2, leg3]

    if leg3["confirmed"]:
        current_phase = "impulse"
    else:
        current_phase = "retracement"

    return {
        "trend": trend,
        "trend_start": {
            "price": float(start_price),
            "index": int(start_idx),
            "timestamp": _ensure_utc(_candle_field(start_candle, "timestamp")),
        },
        "legs": legs,
        "current_phase": current_phase,
    }


def _extract_trend_window(override: Any) -> tuple[Optional[datetime], Optional[datetime]]:
    start_ts = _ov_field(override, "trend_start_timestamp")
    end_ts = _ov_field(override, "trend_end_timestamp")

    if start_ts is not None or end_ts is not None:
        return start_ts, end_ts

    trend_bounds = _ov_field(override, "trend_bounds")
    if trend_bounds is not None:
        return (
            _ov_field(trend_bounds, "trend_start_timestamp", _ov_field(trend_bounds, "start_timestamp")),
            _ov_field(trend_bounds, "trend_end_timestamp", _ov_field(trend_bounds, "end_timestamp")),
        )

    return None, None


def resolve_global_override(override: Any, candles: list, trend_direction: str) -> dict | None:
    if override is None or not candles:
        return None

    trend_start, trend_end = _extract_trend_window(override)
    scoped = _filter_candles_by_window(candles, trend_start, trend_end)
    if not scoped:
        return None

    search_radius = int(_ov_field(override, "search_radius", 10))
    snapped_impulse, snapped_retracement = _resolve_boundaries(
        override,
        scoped,
        trend_direction,
        search_radius,
    )
    if snapped_impulse is None or snapped_retracement is None:
        return None

    trend_result = _build_override_trend_result(
        scoped,
        trend_direction,
        snapped_impulse,
        snapped_retracement,
    )
    choch_zone = _build_zone_from_boundaries(snapped_impulse, snapped_retracement, trend_result["trend"])

    return {
        "trend_result": trend_result,
        "choch_zone": choch_zone,
    }


def resolve_prime_override(
    override: Any,
    candles: list,
    trend_direction: str,
    prime_window_start: datetime,
    prime_window_end: datetime,
) -> dict | None:
    if override is None or not candles:
        return None

    scoped = _filter_candles_by_window(candles, prime_window_start, prime_window_end)
    if not scoped:
        return None

    search_radius = int(_ov_field(override, "search_radius", 10))
    snapped_impulse, snapped_retracement = _resolve_boundaries(
        override,
        scoped,
        trend_direction,
        search_radius,
    )
    if snapped_impulse is None or snapped_retracement is None:
        return None

    trend_result = _build_override_trend_result(
        scoped,
        trend_direction,
        snapped_impulse,
        snapped_retracement,
    )
    choch_zone = _build_zone_from_boundaries(snapped_impulse, snapped_retracement, trend_result["trend"])

    return {
        "trend_result": trend_result,
        "choch_zone": choch_zone,
    }


def resolve_walker_depth_override(
    override: Any,
    candles: list,
    depth_index: int,
    trend_direction: str,
) -> dict | None:
    if override is None or not candles:
        return None

    if _ov_field(override, "depth_index") not in {None, depth_index}:
        return None

    search_radius = int(_ov_field(override, "search_radius", 10))
    snapped_impulse, snapped_retracement = _resolve_boundaries(
        override,
        candles,
        trend_direction,
        search_radius,
    )
    if snapped_impulse is None or snapped_retracement is None:
        return None

    lower = min(float(snapped_impulse["snapped_price"]), float(snapped_retracement["snapped_price"]))
    upper = max(float(snapped_impulse["snapped_price"]), float(snapped_retracement["snapped_price"]))
    zone_width_pct = round((upper - lower) / lower * 100, 2) if lower != 0 else 0.0
    zone_midpoint = (lower + upper) / 2.0

    return {
        "lower_boundary": lower,
        "upper_boundary": upper,
        "zone_width_pct": zone_width_pct,
        "zone_midpoint": zone_midpoint,
        "trend_direction": trend_direction.lower().strip(),
        "source": "manual_override_depth",
        "depth_index": int(depth_index),
    }


def resolve_candidate_override(override: Any, candles: list, trend_direction: str) -> dict | None:
    if override is None or not candles:
        return None

    start_ts = _ov_field(override, "start_timestamp")
    end_ts = _ov_field(override, "end_timestamp")
    scoped = _filter_candles_by_window(candles, start_ts, end_ts)
    if not scoped:
        return None

    search_radius = int(_ov_field(override, "search_radius", 10))
    snapped_impulse, snapped_retracement = _resolve_boundaries(
        override,
        scoped,
        trend_direction,
        search_radius,
    )
    if snapped_impulse is None or snapped_retracement is None:
        return None

    trend_result = _build_override_trend_result(
        scoped,
        trend_direction,
        snapped_impulse,
        snapped_retracement,
    )
    choch_zone = _build_zone_from_boundaries(snapped_impulse, snapped_retracement, trend_result["trend"])

    return {
        "trend_result": trend_result,
        "choch_zone": choch_zone,
    }
