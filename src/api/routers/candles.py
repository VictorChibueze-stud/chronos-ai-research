from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.cache import candle_store
from src.db.session import get_db


router = APIRouter(prefix="/api/candles", tags=["candles"])
logger = logging.getLogger(__name__)


class CandleRefreshRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=1)
    timeframes: list[str] = Field(..., min_length=1)


@router.get("/cache/stats")
def get_candle_cache_stats(db: Session = Depends(get_db)) -> dict:
    return candle_store.get_cache_stats(db)


@router.post("/refresh")
def start_candle_cache_refresh(body: CandleRefreshRequest) -> dict:
    import threading

    syms = [s.upper() for s in body.symbols]
    tfs = [t.lower() for t in body.timeframes]

    def run() -> None:
        candle_store.refresh_all_symbols(syms, tfs, None)

    threading.Thread(target=run, daemon=True).start()
    return {
        "status": "refresh_started",
        "symbol_count": len(syms),
        "timeframe_count": len(tfs),
    }


@router.get("/{symbol}")
def get_candles(
    symbol: str,
    timeframe: str = Query("1h"),
    limit: int = Query(
        default=0,
        ge=0,
        description="Max candles to return. 0 means all.",
    ),
    db: Session = Depends(get_db),
) -> list[dict[str, str | float]]:
    symbol_upper = symbol.upper()
    timeframe_lower = timeframe.lower()

    try:
        if limit > 0:
            rows = candle_store._query_candles(
                db, symbol_upper, timeframe_lower, limit
            )
            if not rows:
                candle_store.refresh_candles(
                    symbol_upper, timeframe_lower, db
                )
                rows = candle_store._query_candles(
                    db, symbol_upper, timeframe_lower, limit
                )
            if not rows:
                raise candle_store.CandleDataError(
                    reason="no_data_for_symbol_timeframe",
                    message=(
                        f"No candle data available for {symbol_upper} "
                        f"{timeframe_lower}"
                    ),
                    status_code=404,
                )
            return [
                {
                    "time": c.timestamp.isoformat(),
                    "open": float(c.open),
                    "high": float(c.high),
                    "low": float(c.low),
                    "close": float(c.close),
                    "volume": float(c.volume),
                }
                for c in rows
            ]

        candles = candle_store.get_candles(
            symbol_upper,
            timeframe_lower,
            db,
            limit=0,
        )
    except candle_store.CandleDataError as exc:
        logger.warning(
            "candle_request_failed symbol=%s timeframe=%s reason=%s status=%s message=%s",
            symbol_upper,
            timeframe_lower,
            exc.reason,
            exc.status_code,
            exc,
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "reason": exc.reason,
                "message": str(exc),
                "symbol": symbol_upper,
                "timeframe": timeframe_lower,
            },
        ) from exc
    except Exception as exc:
        logger.exception(
            "candle_request_unhandled_error symbol=%s timeframe=%s",
            symbol_upper,
            timeframe_lower,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "reason": "unknown_upstream_error",
                "message": str(exc),
                "symbol": symbol_upper,
                "timeframe": timeframe_lower,
            },
        ) from exc

    return [
        {
            "time": candle.timestamp.isoformat(),
            "open": float(candle.open),
            "high": float(candle.high),
            "low": float(candle.low),
            "close": float(candle.close),
            "volume": float(candle.volume),
        }
        for candle in candles
    ]


@router.get("/{symbol}/info")
def get_candles_info(
    symbol: str,
    timeframe: str = Query("1h"),
    db: Session = Depends(get_db),
) -> dict:
    """Lightweight metadata probe: candle count + date range.

    Lets the frontend decide whether to issue a full-history fetch
    after an initial limited load has already populated the chart.
    """
    try:
        candles = candle_store.get_candles(
            symbol.upper(), timeframe.lower(), db
        )
        if not candles:
            return {
                "count": 0,
                "earliest": None,
                "latest": None,
            }
        return {
            "count": len(candles),
            "earliest": candles[0].timestamp.isoformat(),
            "latest": candles[-1].timestamp.isoformat(),
        }
    except Exception:
        return {
            "count": 0,
            "earliest": None,
            "latest": None,
        }
