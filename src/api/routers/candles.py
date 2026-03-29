from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from src.adapters.binance_data import fetch_binance_ohlc_sync
from src.adapters.deriv_data import fetch_deriv_ohlc_sync


router = APIRouter(prefix="/api/candles", tags=["candles"])


def _resample_deriv_candles(
    candles: list,
    bucket_minutes: int,
) -> list:
    if not candles:
        return []

    # Group 1m candles into fixed UTC buckets and aggregate OHLCV.
    buckets: dict[int, list] = {}
    bucket_seconds = bucket_minutes * 60
    for candle in candles:
        ts = candle.timestamp
        epoch = int(ts.replace(tzinfo=timezone.utc).timestamp())
        bucket_start = epoch - (epoch % bucket_seconds)
        buckets.setdefault(bucket_start, []).append(candle)

    resampled = []
    for bucket_start in sorted(buckets.keys()):
        group = buckets[bucket_start]
        if not group:
            continue
        group_sorted = sorted(group, key=lambda c: c.timestamp)
        first = group_sorted[0]
        last = group_sorted[-1]
        high = max(c.high for c in group_sorted)
        low = min(c.low for c in group_sorted)
        volume = sum(float(c.volume) for c in group_sorted)

        resampled.append(
            type(first)(
                timestamp=datetime.fromtimestamp(bucket_start, tz=timezone.utc),
                open=float(first.open),
                high=float(high),
                low=float(low),
                close=float(last.close),
                volume=float(volume),
            )
        )

    return resampled


@router.get("/{symbol}")
async def get_candles(
    symbol: str,
    timeframe: str = Query("1h"),
    limit: int = Query(200, ge=1, le=500),
) -> list[dict[str, str | float]]:
    symbol_upper = symbol.upper()
    timeframe_lower = timeframe.lower()
    is_binance = symbol_upper.endswith("USDT") or symbol_upper.endswith("BTC")

    if is_binance:
        fetch_fn = lambda: fetch_binance_ohlc_sync(symbol_upper, timeframe_lower)
    else:
        if timeframe_lower == "30m":
            # Deriv does not support 30m natively.
            # Fetch 15m and resample to 30m.
            now = datetime.now(timezone.utc)
            lookback_minutes = 30 * limit
            start_time = now - timedelta(minutes=lookback_minutes + 30)

            def fetch_fn():
                base = fetch_deriv_ohlc_sync(symbol_upper, "15m", start_time=start_time)
                return _resample_deriv_candles(base, 30)
        else:
            fetch_fn = lambda: fetch_deriv_ohlc_sync(symbol_upper, timeframe_lower)

    try:
        loop = asyncio.get_event_loop()
        candles = await loop.run_in_executor(None, fetch_fn)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Data unavailable for symbol={symbol_upper} timeframe={timeframe_lower}",
        ) from exc

    trimmed = candles[-limit:]
    return [
        {
            "time": candle.timestamp.isoformat(),
            "open": float(candle.open),
            "high": float(candle.high),
            "low": float(candle.low),
            "close": float(candle.close),
            "volume": float(candle.volume),
        }
        for candle in trimmed
    ]
