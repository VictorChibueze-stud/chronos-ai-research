from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.adapters.binance_data import fetch_binance_ohlc_sync
from src.adapters.deriv_data import fetch_deriv_ohlc_sync
from src.api.routers.setups import _infer_category
from src.core.structural_walker import serialize_state_report, walk_structure
from src.core.trend_id import compute_internal_structure, identify_trend
from src.db.models import MonitoredSetup
from src.db.session import get_db


router = APIRouter(prefix="/api/analysis", tags=["analysis"])
universe_router = APIRouter(prefix="/api/universe", tags=["analysis"])


def _parse_state(raw_value: Any) -> dict[str, Any]:
    if raw_value is None:
        return {}
    if isinstance(raw_value, dict):
        return raw_value
    if isinstance(raw_value, str):
        parsed = json.loads(raw_value)
        if isinstance(parsed, dict):
            return parsed
    return {}


@universe_router.get("/stats")
def get_universe_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
    setups = db.query(MonitoredSetup).all()

    by_category: dict[str, dict[str, int]] = {
        "crypto": {"count": 0, "trending_up": 0, "trending_down": 0},
        "forex": {"count": 0, "trending_up": 0, "trending_down": 0},
        "commodity": {"count": 0, "trending_up": 0, "trending_down": 0},
        "synthetic": {"count": 0, "trending_up": 0, "trending_down": 0},
    }
    by_phase = {"impulse": 0, "retracement": 0, "range": 0}
    by_depth = {"depth_1": 0, "depth_2": 0, "depth_3": 0}

    for setup in setups:
        category = _infer_category(setup.symbol)
        trend = (setup.htf_trend_direction or "").lower()
        if category in by_category:
            by_category[category]["count"] += 1
            if trend == "up":
                by_category[category]["trending_up"] += 1
            elif trend == "down":
                by_category[category]["trending_down"] += 1

        phase = (setup.current_phase or "range").lower()
        if phase not in {"impulse", "retracement", "range"}:
            phase = "range"
        by_phase[phase] += 1

        state = _parse_state(setup.structural_state_json)
        max_depth = int(state.get("max_depth_reached", 0) or 0)
        if max_depth == 1:
            by_depth["depth_1"] += 1
        elif max_depth == 2:
            by_depth["depth_2"] += 1
        elif max_depth >= 3:
            by_depth["depth_3"] += 1

    return {
        "total_monitored": len(setups),
        "by_category": by_category,
        "by_phase": by_phase,
        "by_depth": by_depth,
    }


@router.get("/{symbol}/move")
def get_move_analysis(
    symbol: str,
    start: str,
    end: str | None = None,
    timeframe: str = "auto",
) -> dict[str, Any]:
    symbol_upper = symbol.upper()

    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid start: {exc}") from exc

    if end is None:
        end_dt = datetime.now(timezone.utc)
    else:
        try:
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid end: {exc}") from exc

    is_binance = symbol_upper.endswith("USDT") or symbol_upper.endswith("BTC")

    filter_config = {
        "use_parent_relative_filter": True,
        "min_impulse_parent_ratio": 0.15,
        "use_momentum_filter": True,
        "min_momentum_ratio": 0.5,
        "use_dominance_filter": True,
        "min_dominance_ratio": 1.5,
    }
    auto_tf_order = ["4h", "1h", "15m", "5m"]
    min_legs = 3

    def _fetch_slice(tf: str) -> list:
        if is_binance:
            all_candles = fetch_binance_ohlc_sync(symbol_upper, tf, start_time=start_dt)
        else:
            all_candles = fetch_deriv_ohlc_sync(symbol_upper, tf, start_time=start_dt)
        return [c for c in all_candles if start_dt <= c.timestamp <= end_dt]

    def _analyze(candles: list) -> dict:
        result = identify_trend(candles, **filter_config)
        compute_internal_structure(candles, result["legs"], **filter_config)
        return result

    def _count_confirmed(result: dict) -> int:
        outer = [l for l in result["legs"] if l.get("confirmed")]
        internal = [
            il
            for l in result["legs"]
            for il in (l.get("internal_structure") or {}).get("legs", [])
            if il.get("confirmed")
        ]
        return len(outer) + len(internal)

    selected_tf: str | None = None
    selected_candles: list | None = None
    selected_result: dict | None = None

    if timeframe == "auto":
        for tf in auto_tf_order:
            try:
                tf_candles = _fetch_slice(tf)
            except Exception:
                continue
            if len(tf_candles) < 100:
                continue
            tf_result = _analyze(tf_candles)
            if _count_confirmed(tf_result) >= min_legs:
                selected_tf = tf
                selected_candles = tf_candles
                selected_result = tf_result
                break
        if selected_tf is None:
            raise HTTPException(
                status_code=422,
                detail="No timeframe found 3+ confirmed legs. Widen the date range or lower MIN_LEGS.",
            )
    else:
        try:
            selected_candles = _fetch_slice(timeframe)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Fetch failed: {exc}") from exc
        if not selected_candles:
            raise HTTPException(status_code=422, detail="No candles in the specified range.")
        selected_tf = timeframe
        selected_result = _analyze(selected_candles)

    try:
        state_report = walk_structure(
            selected_candles,
            selected_result,
            filter_config,
            max_depth=3,
            binance_symbol=symbol_upper if is_binance else None,
        )
        structural_state = serialize_state_report(state_report)
    except Exception:
        structural_state = {}

    confirmed_legs = [
        {
            "type": leg["type"],
            "start_price": leg["start_price"],
            "end_price": leg["end_price"],
            "start_index": leg["start_index"],
            "end_index": leg["end_index"],
            "confirmed": leg["confirmed"],
        }
        for leg in selected_result["legs"]
        if leg.get("confirmed")
    ]

    return {
        "symbol": symbol_upper,
        "timeframe_used": selected_tf,
        "candle_count": len(selected_candles),
        "trend": selected_result["trend"],
        "current_phase": selected_result["current_phase"],
        "confirmed_legs": confirmed_legs,
        "structural_state": structural_state,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
    }


@router.get("/{symbol}")
def get_analysis(
    symbol: str,
    timeframe: str = "1h",
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    symbol_upper = symbol.upper()
    timeframe_lower = timeframe.lower()

    setup = (
        db.query(MonitoredSetup)
        .filter(MonitoredSetup.symbol == symbol_upper)
        .order_by(MonitoredSetup.trend_score.desc(), MonitoredSetup.id.asc())
        .first()
    )
    if setup is None:
        return {
            "status": "not_found",
            "symbol": symbol_upper,
        }

    stored_tf = (setup.htf_timeframe or "").lower()
    if timeframe_lower == stored_tf:
        state = _parse_state(setup.structural_state_json)
        max_depth_reached = int(state.get("max_depth_reached", 0) or 0)
        total_mitigation_count = int(state.get("total_mitigation_count", 0) or 0)
        waiting_for = state.get("waiting_for", "")
        global_trend = state.get("global_trend", setup.htf_trend_direction or "range")

        return {
            "status": "ok",
            "symbol": symbol_upper,
            "timeframe": setup.htf_timeframe,
            "global_trend": global_trend,
            "max_depth_reached": max_depth_reached,
            "total_mitigation_count": total_mitigation_count,
            "waiting_for": waiting_for,
            "structural_state": state,
            "live_computed": False,
        }

    is_binance = symbol_upper.endswith("USDT") or symbol_upper.endswith("BTC")
    filter_config = {
        "use_parent_relative_filter": True,
        "min_impulse_parent_ratio": 0.15,
        "use_momentum_filter": True,
        "min_momentum_ratio": 0.5,
        "use_dominance_filter": True,
        "min_dominance_ratio": 1.5,
    }

    try:
        if is_binance:
            candles = fetch_binance_ohlc_sync(symbol_upper, timeframe_lower)
        else:
            candles = fetch_deriv_ohlc_sync(symbol_upper, timeframe_lower)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Data unavailable for symbol={symbol_upper} timeframe={timeframe_lower}: {exc}",
        ) from exc

    if not candles:
        raise HTTPException(
            status_code=422,
            detail=f"No candles returned for symbol={symbol_upper} timeframe={timeframe_lower}",
        )

    result = identify_trend(candles, **filter_config)
    compute_internal_structure(candles, result["legs"], **filter_config)
    state_report = walk_structure(
        candles,
        result,
        filter_config,
        max_depth=3,
        binance_symbol=symbol_upper if is_binance else None,
    )
    state = serialize_state_report(state_report)
    max_depth_reached = int(state.get("max_depth_reached", 0) or 0)
    total_mitigation_count = int(state.get("total_mitigation_count", 0) or 0)
    waiting_for = state.get("waiting_for", "")
    global_trend = state.get("global_trend", result.get("trend", "range"))

    return {
        "status": "ok",
        "symbol": symbol_upper,
        "timeframe": timeframe_lower,
        "global_trend": global_trend,
        "max_depth_reached": max_depth_reached,
        "total_mitigation_count": total_mitigation_count,
        "waiting_for": waiting_for,
        "structural_state": state,
        "live_computed": True,
    }