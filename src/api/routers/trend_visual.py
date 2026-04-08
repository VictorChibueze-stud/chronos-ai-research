"""
Standalone trend start visual testing endpoint.
Returns trend start data for display on the frontend chart.
Does not affect any existing functionality.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.api.routers.analysis import (
    FILTER_CONFIG,
    _enrich_internal_structure_with_tf_deepening,
    _serialize_trend_legs_structure,
)
from src.cache import candle_store
from src.db.session import get_db
from src.core.structure_levels import compute_all_structure_levels, compute_internal_structure_levels
from src.core.trend_id import compute_internal_structure, identify_trend
from src.core.trend_start import find_trend_start

router = APIRouter(prefix="/api/trend-visual", tags=["trend-visual"])


def _candles_since(
    db: Session,
    symbol_upper: str,
    tf: str,
    start_time: datetime,
) -> list:
    try:
        all_candles = candle_store.get_candles(symbol_upper, tf.lower(), db)
    except candle_store.CandleDataError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"reason": exc.reason, "message": str(exc)},
        ) from exc
    out = []
    for c in all_candles:
        ts = c.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= start_time:
            out.append(c)
    return out


@router.get("/{symbol}/structure")
def get_trend_structure(
    symbol: str,
    timeframe: str = Query("1h"),
    db: Session = Depends(get_db),
) -> dict:
    symbol_upper = symbol.upper()
    lookback_map = {"1h": 365, "4h": 730, "1d": 2190, "1w": 365 * 5, "1mo": 365 * 10}
    lookback_days = lookback_map.get(timeframe.lower(), 365)
    start_time = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    candles = _candles_since(db, symbol_upper, timeframe.lower(), start_time)

    if not candles:
        raise HTTPException(status_code=422, detail="No candles returned")

    trend_info = find_trend_start(candles)
    if trend_info is None:
        raise HTTPException(status_code=422, detail="No trend found")

    start_idx = int(trend_info["start_index"])
    window_candles = candles[start_idx:]
    if len(window_candles) < 10:
        raise HTTPException(status_code=422, detail="Trend window too short")

    result = identify_trend(window_candles, **FILTER_CONFIG)
    compute_internal_structure(window_candles, result["legs"], **FILTER_CONFIG)
    _enrich_internal_structure_with_tf_deepening(
        window_candles, result["legs"], FILTER_CONFIG, symbol_upper
    )
    compute_internal_structure_levels(window_candles, result["legs"])

    _ = compute_all_structure_levels(
        window_candles, result.get("legs") or [], result.get("trend", "range")
    )

    payload = _serialize_trend_legs_structure(window_candles, result)
    gz = payload.get("global_choch_zone")
    choch_zone = None
    if gz:
        choch_zone = {
            "depth": 1,
            "lower_boundary": float(gz["lower_boundary"]),
            "upper_boundary": float(gz["upper_boundary"]),
            "start_timestamp": gz["start_timestamp"],
            "end_timestamp": gz["end_timestamp"],
            "color": str(gz.get("color") or "#E91E63"),
        }

    return {
        "symbol": symbol_upper,
        "timeframe": timeframe.lower(),
        "trend": result.get("trend"),
        "current_phase": result.get("current_phase"),
        "trend_start_price": trend_info["start_price"],
        "trend_start_timestamp": trend_info["start_timestamp"].isoformat(),
        "candle_count": len(window_candles),
        "legs": payload["legs"],
        "bos_levels": payload["bos_levels"],
        "choch_level": payload["choch_level"],
        "choch_zone": choch_zone,
    }


@router.get("/{symbol}")
def get_trend_visual(symbol: str, db: Session = Depends(get_db)) -> dict:
    """
    Run find_trend_start on 1h, 4h, and 1d for the symbol.
    Returns one trend result per timeframe for visual testing.
    """
    symbol_upper = symbol.upper()
    lookback_map = {
        "1h": 365,
        "4h": 730,
        "1d": 2190,
    }

    results = {}
    for tf, lookback_days in lookback_map.items():
        start_time = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        try:
            candles = _candles_since(db, symbol_upper, tf, start_time)
        except HTTPException as exc:
            results[tf] = {"error": exc.detail}
            continue
        if not candles:
            results[tf] = {"error": "no candles"}
            continue
        result = find_trend_start(candles)
        if result is None:
            results[tf] = {"trend": None, "candle_count": len(candles)}
            continue
        results[tf] = {
            "trend": result["trend"],
            "start_price": result["start_price"],
            "start_timestamp": result["start_timestamp"].isoformat(),
            "start_index": result["start_index"],
            "current_price": result["current_price"],
            "current_timestamp": result["current_timestamp"].isoformat(),
            "move_pct": result["move_pct"],
            "candle_count": len(candles),
        }

    return {"symbol": symbol_upper, "timeframes": results}
