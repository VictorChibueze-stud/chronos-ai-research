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
    "SPX500": "^GSPC",
    "NAS100": "^NDX",
    "DAX40": "^GDAXI",
    "FTSE100": "^FTSE",
    "NKY225": "^N225",
}

# Yahoo Finance practical limits on how far back intraday / daily history extends.
YFINANCE_MAX_LOOKBACK_DAYS: dict[str, float] = {
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "1h": 730,
    "4h": 730,
    "1d": 3650,
    "1w": 3650,
    "1mo": 3650,
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
    df = _flatten_yfinance_columns(df)
    if df.empty:
        return []

    for req in ("open", "high", "low", "close"):
        if req not in df.columns:
            raise RuntimeError(f"yfinance dataframe missing required column {req!r}")

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

    if start_time is not None:
        start = _ensure_utc(start_time)
    else:
        lb_days = _lookback_days(tf if not want_4h else "1h")
        max_days = YFINANCE_MAX_LOOKBACK_DAYS.get(tf, lb_days)
        lb_days = min(lb_days, max_days)
        start = datetime.now(timezone.utc) - timedelta(days=lb_days)

    df = _download_frame(ticker, yf_interval, start)
    candles = _df_to_candles(df)
    if want_4h:
        candles = _resample_ohlc_buckets(candles, 240)

    if not candles:
        raise RuntimeError(f"yfinance returned no OHLC data for {sym_u} ({ticker}) interval={interval}")

    return candles
