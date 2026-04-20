"""
Yahoo Finance adapter for equity indices and commodities.
Uses the yfinance library — no API key required.

Supported symbols (IKENGA internal → Yahoo ticker): SPX500 (^GSPC), NAS100 (^NDX),
DAX40 (^GDAXI), FTSE100 (^FTSE), NKY225 (^N225). Optional futures-style tickers
such as GC=F (gold) and SI=F (silver) can be added to YFINANCE_SYMBOL_MAP when needed.
"""
from __future__ import annotations

import logging
import pathlib
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pandas as pd
import yaml
import yfinance as yf

from src.core.features import Candle

logger = logging.getLogger(__name__)

_TF_WINDOWS_PATH = pathlib.Path(__file__).resolve().parent.parent.parent / "config" / "timeframe_windows.yaml"

TF_MAP: dict[str, str] = {
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "1h",
    "1d": "1d",
    "1w": "1wk",
    "1mo": "1mo",
}

YFINANCE_SYMBOL_MAP: dict[str, str] = {
    # Indices (existing)
    "SPX500": "^GSPC",
    "NAS100": "^NDX",
    "DAX40": "^GDAXI",
    "FTSE100": "^FTSE",
    "NKY225": "^N225",
    # Additional indices
    "HSI": "^HSI",
    "CAC40": "^FCHI",
    "ASX200": "^AXJO",
    # Forex majors
    "FRXEURUSD": "EURUSD=X",
    "FRXGBPUSD": "GBPUSD=X",
    "FRXUSDJPY": "USDJPY=X",
    "FRXUSDCHF": "USDCHF=X",
    "FRXAUDUSD": "AUDUSD=X",
    "FRXUSDCAD": "USDCAD=X",
    "FRXNZDUSD": "NZDUSD=X",
    # Forex major crosses
    "FRXEURGBP": "EURGBP=X",
    "FRXEURJPY": "EURJPY=X",
    "FRXEURCHF": "EURCHF=X",
    "FRXEURAUD": "EURAUD=X",
    "FRXEURCAD": "EURCAD=X",
    "FRXEURNZD": "EURNZD=X",
    "FRXGBPJPY": "GBPJPY=X",
    "FRXGBPCHF": "GBPCHF=X",
    "FRXGBPAUD": "GBPAUD=X",
    "FRXGBPCAD": "GBPCAD=X",
    "FRXGBPNZD": "GBPNZD=X",
    "FRXAUDJPY": "AUDJPY=X",
    "FRXAUDNZD": "AUDNZD=X",
    "FRXAUDCAD": "AUDCAD=X",
    "FRXCADJPY": "CADJPY=X",
    "FRXCHFJPY": "CHFJPY=X",
    "FRXNZDJPY": "NZDJPY=X",
    # Forex minors/exotics
    "FRXUSDSGD": "USDSGD=X",
    "FRXUSDHKD": "USDHKD=X",
    "FRXUSDMXN": "USDMXN=X",
    "FRXUSDSEK": "USDSEK=X",
    "FRXUSDNOK": "USDNOK=X",
    "FRXUSDDKK": "USDDKK=X",
    "FRXEURSEK": "EURSEK=X",
    "FRXEURNOK": "EURNOK=X",
    # Commodities
    "FRXXAUUSD": "GC=F",
    "XAUUSD": "GC=F",
    "XAGUSD": "SI=F",
    "USOIL": "CL=F",
    "UKOIL": "BZ=F",
    "NGAS": "NG=F",
    # Equities
    "AAPL":   "AAPL",
    "MSFT":   "MSFT",
    "GOOGL":  "GOOGL",
    "META":   "META",
    "NVDA":   "NVDA",
    "TSLA":   "TSLA",
    "AMZN":   "AMZN",
    "HD":     "HD",
    "JPM":    "JPM",
    "V":      "V",
    "MA":     "MA",
    "BAC":    "BAC",
    "JNJ":    "JNJ",
    "UNH":    "UNH",
    "PFE":    "PFE",
    "XOM":    "XOM",
    "CVX":    "CVX",
    "CAT":    "CAT",
    "NFLX":   "NFLX",
    "SBUX":   "SBUX",
    # Additional indices
    "US30":   "^DJI",
    "UK100":  "^FTSE",
    "HK50":   "^HSI",
    # Forex exotics
    "FRXUSDZAR": "USDZAR=X",
    "FRXEURTRY": "EURTRY=X",
}

YFINANCE_DISPLAY_NAME_MAP: dict[str, str] = {
    # Equities
    "AAPL":   "Apple Inc.",
    "MSFT":   "Microsoft Corp.",
    "GOOGL":  "Alphabet Inc.",
    "META":   "Meta Platforms",
    "NVDA":   "Nvidia Corp.",
    "TSLA":   "Tesla Inc.",
    "AMZN":   "Amazon.com Inc.",
    "HD":     "Home Depot Inc.",
    "JPM":    "JPMorgan Chase",
    "V":      "Visa Inc.",
    "MA":     "Mastercard Inc.",
    "BAC":    "Bank of America",
    "JNJ":    "Johnson & Johnson",
    "UNH":    "UnitedHealth Group",
    "PFE":    "Pfizer Inc.",
    "XOM":    "ExxonMobil Corp.",
    "CVX":    "Chevron Corp.",
    "CAT":    "Caterpillar Inc.",
    "NFLX":   "Netflix Inc.",
    "SBUX":   "Starbucks Corp.",
    # Indices
    "SPX500":  "S&P 500",
    "NAS100":  "NASDAQ 100",
    "US30":    "Dow Jones 30",
    "DAX40":   "DAX 40",
    "FTSE100": "FTSE 100",
    "UK100":   "FTSE 100",
    "CAC40":   "CAC 40",
    "NKY225":  "Nikkei 225",
    "HSI":     "Hang Seng",
    "HK50":    "Hang Seng 50",
    "ASX200":  "ASX 200",
    # Commodities
    "XAUUSD":    "Gold",
    "FRXXAUUSD": "Gold",
    "XAGUSD":    "Silver",
    "USOIL":     "WTI Crude Oil",
    "UKOIL":     "Brent Crude Oil",
    "NGAS":      "Natural Gas",
    # Forex exotics
    "FRXUSDMXN": "USD/MXN",
    "FRXUSDZAR": "USD/ZAR",
    "FRXEURTRY": "EUR/TRY",
    "FRXUSDSGD": "USD/SGD",
    "FRXUSDHKD": "USD/HKD",
    "FRXUSDSEK": "USD/SEK",
    "FRXUSDNOK": "USD/NOK",
    "FRXUSDDKK": "USD/DKK",
    "FRXEURSEK": "EUR/SEK",
    "FRXEURNOK": "EUR/NOK",
    "FRXGBPNOK": "GBP/NOK",
}

YFINANCE_SECTOR_MAP: dict[str, str] = {
    "AAPL":  "Technology",
    "MSFT":  "Technology",
    "GOOGL": "Technology",
    "META":  "Technology",
    "NVDA":  "Technology",
    "NFLX":  "Technology",
    "TSLA":  "Consumer",
    "AMZN":  "Consumer",
    "HD":    "Consumer",
    "SBUX":  "Consumer",
    "JPM":   "Financial",
    "V":     "Financial",
    "MA":    "Financial",
    "BAC":   "Financial",
    "JNJ":   "Healthcare",
    "UNH":   "Healthcare",
    "PFE":   "Healthcare",
    "XOM":   "Energy",
    "CVX":   "Energy",
    "CAT":   "Industrial",
}


def get_display_name(symbol: str) -> str:
    """Return human-readable display name for symbol."""
    return YFINANCE_DISPLAY_NAME_MAP.get(
        symbol.strip().upper(), symbol.strip().upper()
    )


def get_sector(symbol: str) -> str | None:
    """Return sector for equity symbols, None for others."""
    return YFINANCE_SECTOR_MAP.get(
        symbol.strip().upper()
    )

# Yahoo Finance practical limits on how far back intraday / daily history extends.
YFINANCE_MAX_LOOKBACK_DAYS: dict[str, int] = {
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "1h": 730,
    "4h": 730,
    "1d": 7300,
    "1w": 7300,
    "1mo": 7300,
}

# Hard upper bound on how far back yfinance will actually return data.
# Used to clamp ``start_time`` regardless of caller intent so that
# requests do not silently fail with an out-of-range time window.
YFINANCE_HARD_LIMITS: dict[str, int] = {
    "5m":  60,
    "15m": 60,
    "30m": 60,
    "1h":  729,
    "4h":  729,
    "1d":  7300,
    "1w":  7300,
    "1mo": 7300,
}

_DOWNLOAD_TIMEOUT_SEC = 10.0


def is_yfinance_symbol(symbol: str) -> bool:
    return symbol.strip().upper() in YFINANCE_SYMBOL_MAP


def _lookback_days(timeframe: str) -> float:
    try:
        with _TF_WINDOWS_PATH.open(encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        tfs = cfg.get("timeframes", {})
        if timeframe in tfs and "lookback_days" in tfs[timeframe]:
            return float(tfs[timeframe]["lookback_days"])
    except Exception:
        pass
    defaults: dict[str, float] = {
        "1m": 1.5,
        "5m": 7.5,
        "15m": 25.0,
        "30m": 21.0,
        "1h": 100.0,
        "4h": 365.0,
        "1d": 2190.0,
        "1w": 3650.0,
        "1mo": 7300.0,
    }
    return defaults.get(timeframe, 7.5)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _resample_ohlc_buckets(candles: list[Candle], bucket_minutes: int) -> list[Candle]:
    if not candles:
        return []
    buckets: dict[int, list[Candle]] = {}
    bucket_seconds = bucket_minutes * 60
    for candle in candles:
        ts = candle.timestamp
        epoch = int(ts.replace(tzinfo=timezone.utc).timestamp())
        bucket_start = epoch - (epoch % bucket_seconds)
        buckets.setdefault(bucket_start, []).append(candle)

    resampled: list[Candle] = []
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
            Candle(
                timestamp=datetime.fromtimestamp(bucket_start, tz=timezone.utc),
                open=float(first.open),
                high=float(high),
                low=float(low),
                close=float(last.close),
                volume=float(volume),
            )
        )
    return resampled


def _flatten_yfinance_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [str(c[0]) if isinstance(c, tuple) else str(c) for c in out.columns]
    out.columns = [str(c).lower().replace(" ", "_") for c in out.columns]
    return out


def _df_to_candles(df: pd.DataFrame) -> list[Candle]:
    if df is None or (hasattr(df, "empty") and df.empty):
        return []

    try:
        df = _flatten_yfinance_columns(df)
        if df is None or df.empty:
            return []

        # Drop rows where OHLC columns have NaN. Try lowercase->Capitalized
        # rename if the canonical headers are missing.
        required_cols = ["Open", "High", "Low", "Close"]
        existing_cols = [c for c in required_cols if c in df.columns]
        if len(existing_cols) < 4:
            df = df.rename(columns={
                "open": "Open", "high": "High",
                "low": "Low", "close": "Close",
                "volume": "Volume",
            })
            existing_cols = [
                c for c in required_cols if c in df.columns
            ]
        if len(existing_cols) < 4:
            return []

        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        if df.empty:
            return []

        # yfinance can return capitalized OHLCV headers depending on payload
        # shape. Normalize to lowercase for the rest of the function.
        df.columns = [str(c).lower() for c in df.columns]

        for req in ("open", "high", "low", "close"):
            if req not in df.columns:
                return []

        o, h, low_s, c = df["open"], df["high"], df["low"], df["close"]
        vol = df["volume"] if "volume" in df.columns else pd.Series(0.0, index=df.index)

        candles: list[Candle] = []
        for ts, ov, hv, lv, cv, vv in zip(df.index, o, h, low_s, c, vol):
            if pd.isna(ov) or pd.isna(hv) or pd.isna(lv) or pd.isna(cv):
                continue
            if hasattr(ts, "to_pydatetime"):
                t = ts.to_pydatetime()
            else:
                t = datetime.fromtimestamp(float(pd.Timestamp(ts).timestamp()), tz=timezone.utc)
            t = _ensure_utc(t)
            candles.append(
                Candle(
                    timestamp=t,
                    open=float(ov),
                    high=float(hv),
                    low=float(lv),
                    close=float(cv),
                    volume=float(vv) if not pd.isna(vv) else 0.0,
                )
            )
        candles.sort(key=lambda x: x.timestamp)
        return candles
    except (TypeError, KeyError, AttributeError) as e:
        logger.warning(
            "yfinance _df_to_candles failed: %s", e
        )
        return []


def _download_frame(ticker: str, yf_interval: str, start: Optional[datetime]) -> pd.DataFrame:
    def _run() -> pd.DataFrame:
        kwargs: dict = {
            "tickers": ticker,
            "interval": yf_interval,
            "progress": False,
            "auto_adjust": False,
            "threads": False,
        }
        if start is not None:
            kwargs["start"] = _ensure_utc(start)
        return yf.download(**kwargs)

    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_run)
        try:
            return fut.result(timeout=_DOWNLOAD_TIMEOUT_SEC)
        except FuturesTimeoutError as e:
            raise TimeoutError(f"yfinance download timed out after {_DOWNLOAD_TIMEOUT_SEC:.0f}s for {ticker}") from e


def fetch_yfinance_ohlc_sync(
    symbol: str,
    interval: str,
    start_time: Optional[datetime] = None,
) -> List[Candle]:
    """
    Fetch OHLC from Yahoo Finance for an IKENGA internal symbol.

    Maps symbol to Yahoo ticker, downloads with a 10s timeout, returns Candle list
    sorted ascending. Raises if no rows after filtering NaNs.

    For IKENGA ``4h``, downloads ``1h`` bars and resamples to 4-hour buckets.
    """
    sym_u = symbol.strip().upper()
    ticker = YFINANCE_SYMBOL_MAP.get(sym_u)
    if not ticker:
        raise ValueError(f"Unknown yfinance symbol: {symbol}")

    tf = interval.lower()
    if tf not in TF_MAP:
        raise ValueError(
            f"Unsupported yfinance interval '{interval}'. Supported: {sorted(TF_MAP.keys())}"
        )

    yf_interval = TF_MAP[tf]
    want_4h = tf == "4h"

    # Yahoo Finance does not reliably serve sub-30m bars for forex pairs
    # (=X tickers). Convert the silent empty response into an explicit
    # ValueError so callers / cache layers can skip cleanly.
    is_forex_ticker = ticker.endswith("=X")
    if is_forex_ticker and tf in ("5m", "15m"):
        raise ValueError(
            f"yfinance does not support {tf} for "
            f"forex pair {symbol} ({ticker}). "
            f"Use 30m or higher."
        )

    if start_time is not None:
        start = _ensure_utc(start_time)
    else:
        lb_days = _lookback_days(tf if not want_4h else "1h")
        max_days = YFINANCE_MAX_LOOKBACK_DAYS.get(tf, lb_days)
        lb_days = min(lb_days, max_days)
        start = datetime.now(timezone.utc) - timedelta(days=lb_days)

    # Hard clamp ``start`` to Yahoo Finance's actual retention window for
    # this timeframe. Prevents requests that would silently return empty
    # data because the candle cache's start_timestamp pre-dates Yahoo's
    # retention.
    hard_limit_days = YFINANCE_HARD_LIMITS.get(
        tf if not want_4h else "1h", 730
    )
    earliest_allowed = datetime.now(timezone.utc) - timedelta(
        days=hard_limit_days - 1
    )
    if start < earliest_allowed:
        start = earliest_allowed

    df = _download_frame(ticker, yf_interval, start)
    candles = _df_to_candles(df)
    if want_4h:
        candles = _resample_ohlc_buckets(candles, 240)

    if not candles:
        raise RuntimeError(f"yfinance returned no OHLC data for {sym_u} ({ticker}) interval={interval}")

    return candles
