"""Binance REST API data adapter: fetch OHLC with pagination support.

This module provides async and sync functions to fetch historical OHLC candles
from Binance's public REST API (no auth required). Pagination handles lookback
windows larger than 1000 candles using exponential backoff retry logic.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import pathlib
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import aiohttp
import yaml

from src.core.features import Candle

# Setup logging
logger = logging.getLogger(__name__)

# Config path
_TF_WINDOWS_PATH = pathlib.Path(__file__).parent.parent.parent / "config" / "timeframe_windows.yaml"

# Interval to minutes mapping
INTERVAL_TO_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

BINANCE_API_BASE = "https://api.binance.com/api/v3"
MAX_CANDLES_PER_REQUEST = 1000
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 1


def _load_config() -> Dict[str, Any]:
    """Load timeframe_windows.yaml."""
    try:
        with open(_TF_WINDOWS_PATH) as fh:
            return yaml.safe_load(fh) or {}
    except Exception as e:
        logger.warning(f"Failed to load {_TF_WINDOWS_PATH}: {e}. Using empty config.")
        return {}


def _get_lookback_days(interval: str) -> float:
    """Get lookback_days for an interval from config, default to a sensible value."""
    cfg = _load_config()
    tfs = cfg.get("timeframes", {})
    if interval in tfs and "lookback_days" in tfs[interval]:
        return float(tfs[interval]["lookback_days"])
    # Default lookbacks if not in config
    defaults = {
        "1m": 1.5,
        "5m": 7.5,
        "15m": 25.0,
        "30m": 45.0,
        "1h": 100.0,
        "4h": 365.0,
        "1d": 2190.0,
    }
    return defaults.get(interval, 7.5)


def _compute_candle_count(lookback_days: float, interval_minutes: int) -> int:
    """Compute how many candles are needed for the lookback period."""
    total_minutes = lookback_days * 1440
    import math
    return math.ceil(total_minutes / interval_minutes)


def _parse_kline(kline: List) -> Candle:
    """Parse a Binance kline array into a Candle object.

    Binance kline format:
    0 = open time (ms)
    1 = open (str)
    2 = high (str)
    3 = low (str)
    4 = close (str)
    5 = volume (str)
    """
    open_time_ms = int(kline[0])
    timestamp = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc)

    return Candle(
        timestamp=timestamp,
        open=float(kline[1]),
        high=float(kline[2]),
        low=float(kline[3]),
        close=float(kline[4]),
        volume=float(kline[5]),
    )


async def fetch_binance_ohlc(
    symbol: str,
    interval: str,
    start_time: Optional[datetime] = None,
) -> List[Candle]:
    """Fetch OHLC candles from Binance with automatic pagination.

    Args:
        symbol: Binance trading pair (e.g., "BTCUSDT")
        interval: Candle interval (e.g., "1h"). Must be in INTERVAL_TO_MINUTES.
        start_time: If provided, fetch forward from this UTC datetime instead of
            performing a full lookback-based backward fetch.

    Returns:
        List of Candle objects sorted ascending by timestamp.

    Raises:
        ValueError: If interval is not supported.
        aiohttp.ClientError: If all retries fail.
    """
    if interval not in INTERVAL_TO_MINUTES:
        raise ValueError(
            f"Unsupported interval '{interval}'. Supported: {list(INTERVAL_TO_MINUTES.keys())}"
        )

    interval_minutes = INTERVAL_TO_MINUTES[interval]
    lookback_days = _get_lookback_days(interval)
    candle_count = _compute_candle_count(lookback_days, interval_minutes)

    logger.debug(
        f"Fetching {symbol} {interval}: "
        f"lookback={lookback_days} days, need {candle_count} candles"
    )

    all_candles: List[Candle] = []
    page_num = 1

    if start_time is not None:
        # --- Forward pagination from start_time ---
        # Fetch all candles since the given timestamp, paging forward.
        params: Dict[str, Any] = {
            "symbol": symbol,
            "interval": interval,
            "limit": MAX_CANDLES_PER_REQUEST,
            "startTime": int(start_time.timestamp() * 1000),
        }
        while True:
            klines = await _fetch_klines_with_retry(params)
            if not klines:
                logger.debug(f"Page {page_num}: No more data from API")
                break

            page_candles = [_parse_kline(kline) for kline in klines]
            all_candles.extend(page_candles)
            logger.debug(
                f"Page {page_num}: fetched {len(page_candles)} candles, "
                f"latest: {page_candles[-1].timestamp}, "
                f"total so far: {len(all_candles)}"
            )

            if len(page_candles) < MAX_CANDLES_PER_REQUEST:
                break

            # Advance past the last returned candle
            latest_ts = page_candles[-1].timestamp
            params["startTime"] = int(latest_ts.timestamp() * 1000) + 1
            page_num += 1
    else:
        # --- Backward pagination for full lookback ---
        end_time: Optional[int] = None  # None means most recent

        while len(all_candles) < candle_count:
            # Build request params
            params = {
                "symbol": symbol,
                "interval": interval,
                "limit": MAX_CANDLES_PER_REQUEST,
            }
            if end_time is not None:
                params["endTime"] = end_time

            # Fetch with retries
            klines = await _fetch_klines_with_retry(params)

            if not klines:
                logger.debug(f"Page {page_num}: No more data from API")
                break

            # Parse klines to candles
            page_candles = [_parse_kline(kline) for kline in klines]
            all_candles.extend(page_candles)

            logger.debug(
                f"Page {page_num}: fetched {len(page_candles)} candles, "
                f"earliest: {page_candles[0].timestamp}, "
                f"total so far: {len(all_candles)}"
            )

            # Prepare for next page
            if len(page_candles) < MAX_CANDLES_PER_REQUEST:
                # API returned fewer than max, so we've reached the beginning
                break

            earliest_timestamp = page_candles[0].timestamp
            end_time = int(earliest_timestamp.timestamp() * 1000) - 1
            page_num += 1

    # Deduplicate by timestamp and sort
    seen = set()
    unique_candles = []
    for candle in all_candles:
        if candle.timestamp not in seen:
            seen.add(candle.timestamp)
            unique_candles.append(candle)

    unique_candles.sort(key=lambda c: c.timestamp)

    logger.debug(f"Fetched {len(unique_candles)} total candles after deduplication")
    return unique_candles


async def _fetch_klines_with_retry(params: Dict[str, Any]) -> List[List]:
    """Fetch klines from Binance API with exponential backoff retry.

    Args:
        params: Query parameters for the klines endpoint.

    Returns:
        List of kline arrays, or empty list if all retries fail.

    Raises:
        After MAX_RETRIES attempts.
    """
    url = f"{BINANCE_API_BASE}/klines"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logger.debug(f"Successfully fetched klines (attempt {attempt})")
                        return data
                    else:
                        logger.warning(
                            f"HTTP {resp.status} on attempt {attempt}/{MAX_RETRIES}"
                        )
        except aiohttp.ClientError as e:
            logger.warning(
                f"Network error on attempt {attempt}/{MAX_RETRIES}: {e}"
            )
        except asyncio.TimeoutError as e:
            logger.warning(
                f"Timeout on attempt {attempt}/{MAX_RETRIES}: {e}"
            )

        if attempt < MAX_RETRIES:
            wait_time = RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
            logger.debug(f"Retrying in {wait_time}s...")
            await asyncio.sleep(wait_time)

    raise aiohttp.ClientError(
        f"Failed to fetch klines after {MAX_RETRIES} retries: {params}"
    )


def fetch_binance_ohlc_sync(
    symbol: str,
    interval: str,
    start_time: Optional[datetime] = None,
) -> List[Candle]:
    """Synchronous wrapper for fetch_binance_ohlc.

    Args:
        symbol: Binance trading pair (e.g., "BTCUSDT")
        interval: Candle interval (e.g., "1h")
        start_time: If provided, fetch forward from this UTC datetime (incremental).

    Returns:
        List of Candle objects sorted ascending by timestamp.
    """
    def _run_fetch() -> List[Candle]:
        return asyncio.run(fetch_binance_ohlc(symbol, interval, start_time=start_time))

    try:
        # In notebooks/async apps an event loop is already running.
        asyncio.get_running_loop()
    except RuntimeError:
        return _run_fetch()

    # Run on a worker thread to avoid calling asyncio.run() in a running loop.
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(_run_fetch).result()


if __name__ == "__main__":
    # Setup logging for CLI output
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Fetch BTCUSDT 1h candles
    print("Fetching BTCUSDT 1h candles...")
    candles = fetch_binance_ohlc_sync("BTCUSDT", "1h")

    if not candles:
        print("No candles fetched.")
    else:
        print(f"✓ Total candles fetched: {len(candles)}")
        print(f"✓ Date range: {candles[0].timestamp} to {candles[-1].timestamp}")

        # Identify trend
        from src.core.trend_id import identify_trend

        trend_result = identify_trend(candles)
        print(f"✓ Trend direction: {trend_result.get('trend')}")
        print(f"✓ Number of legs: {len(trend_result.get('legs', []))}")
        print(f"✓ Current phase: {trend_result.get('current_phase')}")
