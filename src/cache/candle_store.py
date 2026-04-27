"""
Candle cache manager.
Reads from SQLite cache first. Falls back to live fetch if cache is stale or empty.
Background refresh writes new candles without blocking the request.
"""
from __future__ import annotations

import logging
import pathlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

import yaml
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from src.adapters.binance_data import fetch_binance_ohlc_sync
from src.adapters.deriv_data import fetch_deriv_ohlc_sync
from src.adapters.yfinance_data import fetch_yfinance_ohlc_sync, is_yfinance_symbol
from src.core.features import Candle
from src.db.models import CandleCache
from src.db.session import DATABASE_URL, SessionLocal

logger = logging.getLogger(__name__)

_TF_WINDOWS_PATH = pathlib.Path(__file__).resolve().parent.parent.parent / "config" / "timeframe_windows.yaml"
_STALE_AFTER = timedelta(minutes=15)
_BYTES_PER_ROW_ESTIMATE = 80
_TF_STALE_REFRESH_MINUTES: dict[str, int] = {
    "5m": 1,
    "15m": 2,
    "30m": 2,
    "1h": 5,
    "4h": 15,
    "1d": 60,
    "1w": 240,
    "1mo": 720,
}
_TF_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
    "1w": 604800,
    "1mo": 2592000,
}

# Cap cold-start "recent" window so HTF (e.g. 500×1w) does not request decades of 1d data in one WS session.
_RECENT_FETCH_MAX_LOOKBACK_DAYS: dict[str, float] = {
    "1m": 2.0,
    "5m": 14.0,
    "15m": 45.0,
    "30m": 90.0,
    "1h": 180.0,
    "4h": 730.0,
    "1d": 2190.0,
    "1w": 800.0,
    "1mo": 7300.0,
}

_CACHE_REFRESH_WORKERS = 1 if DATABASE_URL.lower().startswith("sqlite") else 8


# Tracks which (symbol, timeframe) pairs currently have a background refresh
# running. Guarded by ``_refresh_registry_lock``.
#   Key:   (symbol_upper, timeframe_lower)
#   Value: threading.Event that is set when the in-flight refresh completes.
# Prevents duplicate _bg_refresh threads from piling up for the same
# symbol+timeframe and starving the DB connection pool.
_refresh_in_progress: dict[tuple[str, str], threading.Event] = {}
_refresh_registry_lock = threading.Lock()


def _is_refresh_running(symbol: str, timeframe: str) -> bool:
    """Return True if a refresh is already in progress for this pair."""
    key = (symbol.upper(), timeframe.lower())
    with _refresh_registry_lock:
        return key in _refresh_in_progress


def _mark_refresh_started(symbol: str, timeframe: str) -> bool:
    """Attempt to register this symbol+timeframe as being refreshed.

    Returns True if registration succeeded (caller should proceed).
    Returns False if a refresh is already running (caller should skip).
    """
    key = (symbol.upper(), timeframe.lower())
    with _refresh_registry_lock:
        if key in _refresh_in_progress:
            return False
        _refresh_in_progress[key] = threading.Event()
        return True


def _mark_refresh_done(symbol: str, timeframe: str) -> None:
    """Remove the in-progress marker and wake any waiters."""
    key = (symbol.upper(), timeframe.lower())
    with _refresh_registry_lock:
        event = _refresh_in_progress.pop(key, None)
    if event is not None:
        event.set()


class CandleDataError(Exception):
    def __init__(self, reason: str, message: str, status_code: int = 503):
        super().__init__(message)
        self.reason = reason
        self.status_code = status_code


def _classify_fetch_error(exc: Exception, symbol: str, timeframe: str) -> CandleDataError:
    message = str(exc)
    message_lc = message.lower()
    if isinstance(exc, ValueError):
        return CandleDataError(
            reason="unsupported_timeframe",
            message=f"Unsupported timeframe '{timeframe}' for symbol {symbol}",
            status_code=400,
        )
    if "ratelimit" in message_lc or "rate limit" in message_lc or "429" in message_lc:
        return CandleDataError(
            reason="rate_limited",
            message=f"Upstream rate limit while fetching {symbol} {timeframe}",
            status_code=429,
        )
    if "timeout" in message_lc or "timed out" in message_lc:
        return CandleDataError(
            reason="timeout",
            message=f"Upstream timeout while fetching {symbol} {timeframe}",
            status_code=504,
        )
    if isinstance(exc, RuntimeError):
        if "missing deriv credentials" in message_lc:
            return CandleDataError(
                reason="deriv_config_error",
                message=f"Deriv is not configured for {symbol} {timeframe}: {message}",
                status_code=502,
            )
        if "deriv authorization error" in message_lc:
            return CandleDataError(
                reason="deriv_auth_error",
                message=f"Deriv authorization failed for {symbol} {timeframe}: {message}",
                status_code=502,
            )
        if "deriv ohlc error" in message_lc:
            return CandleDataError(
                reason="deriv_api_error",
                message=f"Deriv API rejected or failed OHLC for {symbol} {timeframe}: {message}",
                status_code=502,
            )
    return CandleDataError(
        reason="upstream_fetch_failed",
        message=f"Failed to fetch candles for {symbol} {timeframe}: {message}",
        status_code=503,
    )


def _load_tf_config() -> dict[str, Any]:
    try:
        with _TF_WINDOWS_PATH.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as e:
        logger.warning("Failed to load %s: %s", _TF_WINDOWS_PATH, e)
        return {}


def _lookback_days(timeframe: str) -> float:
    cfg = _load_tf_config()
    tfs = cfg.get("timeframes", {})
    if timeframe in tfs and "lookback_days" in tfs[timeframe]:
        return float(tfs[timeframe]["lookback_days"])
    defaults: dict[str, float] = {
        "1m": 1.5,
        "5m": 60.0,
        "15m": 180.0,
        "30m": 365.0,
        "1h": 730.0,
        "4h": 1460.0,
        "1d": 2190.0,
        "1w": 3650.0,
        "1mo": 7300.0,
    }
    return defaults.get(timeframe, 7.5)


def _is_binance_symbol(symbol: str) -> bool:
    su = symbol.upper()
    return su.endswith("USDT") or su.endswith("BTC")


def _resample_deriv_candles(candles: list[Candle], bucket_minutes: int) -> list[Candle]:
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


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _fetch_live_candles(
    symbol: str,
    timeframe: str,
    *,
    start_time: datetime | None = None,
) -> list[Candle]:
    """Fetch live OHLC. ``start_time`` set => forward fetch from that instant (incremental append)."""
    symbol_u = symbol.upper()
    tf = timeframe.lower()
    if is_yfinance_symbol(symbol_u):
        return fetch_yfinance_ohlc_sync(symbol_u, tf, start_time=start_time)
    if _is_binance_symbol(symbol_u):
        return fetch_binance_ohlc_sync(symbol_u, tf, start_time=start_time)
    if tf == "30m":
        if start_time is not None:
            st = _ensure_utc(start_time)
            base = fetch_deriv_ohlc_sync(symbol_u, "15m", start_time=st)
        else:
            now = datetime.now(timezone.utc)
            lb = _lookback_days("30m")
            st = now - timedelta(days=lb)
            base = fetch_deriv_ohlc_sync(symbol_u, "15m", start_time=st)
        return _resample_deriv_candles(base, 30)
    return fetch_deriv_ohlc_sync(symbol_u, tf, start_time=start_time)


def _fetch_live_candles_recent(symbol: str, timeframe: str, recent_count: int) -> list[Candle]:
    symbol_u = symbol.upper()
    tf = timeframe.lower()
    if is_yfinance_symbol(symbol_u):
        tf_seconds = _TF_SECONDS.get(tf)
        if tf_seconds is None:
            return _fetch_live_candles(symbol_u, tf, start_time=None)
        now = datetime.now(timezone.utc)
        lookback_seconds = max(tf_seconds * recent_count, tf_seconds)
        max_days = _RECENT_FETCH_MAX_LOOKBACK_DAYS.get(tf)
        if max_days is not None:
            cap_seconds = int(max_days * 86400)
            lookback_seconds = min(lookback_seconds, cap_seconds)
        start_time = now - timedelta(seconds=lookback_seconds)
        return fetch_yfinance_ohlc_sync(symbol_u, tf, start_time=start_time)
    if _is_binance_symbol(symbol_u):
        return _fetch_live_candles(symbol_u, tf, start_time=None)
    tf_seconds = _TF_SECONDS.get(tf)
    if tf_seconds is None:
        return _fetch_live_candles(symbol_u, tf)
    now = datetime.now(timezone.utc)
    lookback_seconds = max(tf_seconds * recent_count, tf_seconds)
    max_days = _RECENT_FETCH_MAX_LOOKBACK_DAYS.get(tf)
    if max_days is not None:
        cap_seconds = int(max_days * 86400)
        lookback_seconds = min(lookback_seconds, cap_seconds)
    start_time = now - timedelta(seconds=lookback_seconds)
    if tf == "30m":
        base = fetch_deriv_ohlc_sync(symbol_u, "15m", start_time=start_time)
        return _resample_deriv_candles(base, 30)
    return fetch_deriv_ohlc_sync(symbol_u, tf, start_time=start_time)


def _rows_to_candles(rows: list[CandleCache]) -> list[Candle]:
    return [
        Candle(
            timestamp=r.timestamp,
            open=float(r.open),
            high=float(r.high),
            low=float(r.low),
            close=float(r.close),
            volume=float(r.volume),
        )
        for r in rows
    ]


def lookback_start_time(timeframe: str, *, now: datetime | None = None) -> datetime:
    """UTC instant at the start of the configured lookback window for ``timeframe`` (from YAML / defaults)."""
    tf = timeframe.lower()
    anchor = _ensure_utc(now) if now is not None else datetime.now(timezone.utc)
    return anchor - timedelta(days=_lookback_days(tf))


def get_last_cached_timestamp(symbol: str, timeframe: str, db: Session) -> datetime | None:
    """Return the latest candle open time for ``symbol`` + ``timeframe`` in cache, or ``None`` if empty."""
    sym = symbol.upper()
    tf = timeframe.lower()
    row = (
        db.query(func.max(CandleCache.timestamp))
        .filter(CandleCache.symbol == sym, CandleCache.timeframe == tf)
        .scalar()
    )
    if row is None:
        return None
    return _ensure_utc(row)


def get_earliest_cached_timestamp(symbol: str, timeframe: str, db: Session) -> datetime | None:
    """Return the earliest candle open time for ``symbol`` + ``timeframe`` in cache, or ``None`` if empty."""
    sym = symbol.upper()
    tf = timeframe.lower()
    row = (
        db.query(func.min(CandleCache.timestamp))
        .filter(CandleCache.symbol == sym, CandleCache.timeframe == tf)
        .scalar()
    )
    if row is None:
        return None
    return _ensure_utc(row)


def _upsert_candles(db: Session, symbol: str, timeframe: str, candles: list[Candle]) -> int:
    if not candles:
        return 0
    sym = symbol.upper()
    tf = timeframe.lower()
    now = datetime.now(timezone.utc)
    count = 0
    is_postgres = db.bind is not None and db.bind.dialect.name == "postgresql"
    for c in candles:
        insert_factory = pg_insert if is_postgres else sqlite_insert
        stmt = insert_factory(CandleCache).values(
            symbol=sym,
            timeframe=tf,
            timestamp=c.timestamp,
            open=float(c.open),
            high=float(c.high),
            low=float(c.low),
            close=float(c.close),
            volume=float(c.volume),
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "timeframe", "timestamp"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        db.execute(stmt)
        count += 1
    db.commit()
    return count


def refresh_candles(symbol: str, timeframe: str, db: Session, *, force_full: bool = False) -> int:
    """Upsert candles: incremental from last cache row when present, else full lookback.

    If ``force_full`` is True, always fetch the full configured lookback (ignores cache for fetch range).
    """
    sym = symbol.upper()
    tf = timeframe.lower()
    last = get_last_cached_timestamp(sym, tf, db)
    try:
        if force_full:
            logger.info("refresh_candles force_full symbol=%s timeframe=%s (full lookback)", sym, tf)
            candles = _fetch_live_candles(sym, tf, start_time=None)
        elif last is None:
            logger.info("refresh_candles cold symbol=%s timeframe=%s (full lookback)", sym, tf)
            candles = _fetch_live_candles(sym, tf, start_time=None)
        else:
            since = _ensure_utc(last) + timedelta(milliseconds=1)
            logger.info(
                "refresh_candles incremental symbol=%s timeframe=%s since=%s",
                sym,
                tf,
                since.isoformat(),
            )
            candles = _fetch_live_candles(sym, tf, start_time=since)
    except Exception as e:
        logger.warning(
            "refresh_candles fetch failed symbol=%s timeframe=%s reason=%s",
            symbol,
            timeframe,
            _classify_fetch_error(e, symbol, timeframe).reason,
        )
        return 0
    if not candles:
        return 0
    return _upsert_candles(db, symbol, timeframe, candles)


def refresh_candles_recent(symbol: str, timeframe: str, db: Session, recent_count: int = 500) -> int:
    """Upsert candles: incremental from last cache row when present; else bounded recent window."""
    sym = symbol.upper()
    tf = timeframe.lower()
    last = get_last_cached_timestamp(sym, tf, db)
    try:
        if last is not None:
            since = _ensure_utc(last) + timedelta(milliseconds=1)
            logger.info(
                "refresh_candles_recent incremental symbol=%s timeframe=%s since=%s",
                sym,
                tf,
                since.isoformat(),
            )
            candles = _fetch_live_candles(sym, tf, start_time=since)
        else:
            logger.debug(
                "refresh_candles_recent cold symbol=%s timeframe=%s (bounded recent)",
                sym,
                tf,
            )
            candles = _fetch_live_candles_recent(symbol, timeframe, recent_count=recent_count)
    except Exception as e:
        logger.warning(
            "refresh_candles_recent fetch failed symbol=%s timeframe=%s reason=%s",
            symbol,
            timeframe,
            _classify_fetch_error(e, symbol, timeframe).reason,
        )
        return 0
    if not candles:
        return 0
    return _upsert_candles(db, symbol, timeframe, candles)


def _bg_refresh(symbol: str, timeframe: str) -> None:
    # Deduplicate: if a refresh is already running for this symbol+timeframe,
    # skip — the in-flight thread will write the latest data anyway.
    if not _mark_refresh_started(symbol, timeframe):
        logger.debug(
            "Skipping duplicate bg_refresh %s %s — already in progress",
            symbol,
            timeframe,
        )
        return

    db = SessionLocal()
    try:
        n = refresh_candles(symbol, timeframe, db)
        logger.info("Cache refresh (background): %s %s — %s candles written", symbol, timeframe, n)
    except Exception as e:
        logger.warning("Cache background refresh failed %s %s: %s", symbol, timeframe, e)
    finally:
        db.close()
        _mark_refresh_done(symbol, timeframe)


def _query_candles(
    db: Session, sym: str, tf: str, limit: int
) -> list[CandleCache]:
    """Fetch CandleCache rows in ascending timestamp order.

    When ``limit > 0`` the database does the work via ``ORDER BY timestamp DESC
    LIMIT N`` (which uses the timestamp index efficiently), then we reverse in
    Python to restore ascending order. This avoids materialising thousands of
    Candle objects when the caller only needs the most recent N.
    """
    if limit > 0:
        rows = (
            db.query(CandleCache)
            .filter(CandleCache.symbol == sym, CandleCache.timeframe == tf)
            .order_by(CandleCache.timestamp.desc())
            .limit(limit)
            .all()
        )
        return list(reversed(rows))
    return (
        db.query(CandleCache)
        .filter(CandleCache.symbol == sym, CandleCache.timeframe == tf)
        .order_by(CandleCache.timestamp.asc())
        .all()
    )


def get_candles(
    symbol: str,
    timeframe: str,
    db: Session,
    limit: int = 0,
) -> list[Candle]:
    """Return cached candles ascending; ``limit > 0`` returns just the last N."""
    sym = symbol.upper()
    tf = timeframe.lower()
    rows = _query_candles(db, sym, tf, limit)
    now = datetime.now(timezone.utc)

    if not rows:
        logger.info("candle_cache_miss symbol=%s timeframe=%s", sym, tf)
        try:
            recent_candles = _fetch_live_candles_recent(sym, tf, recent_count=500)
        except Exception as e:
            raise _classify_fetch_error(e, sym, tf) from e
        if not recent_candles:
            raise CandleDataError(
                reason="no_data_for_symbol_timeframe",
                message=f"No candle data available for {sym} {tf}",
                status_code=404,
            )
        _upsert_candles(db, sym, tf, recent_candles)
        # Decouple deep history fetch from the request path.
        threading.Thread(target=_bg_refresh, args=(sym, tf), daemon=True).start()
        rows = _query_candles(db, sym, tf, limit)
        if not rows:
            raise CandleDataError(
                reason="no_data_for_symbol_timeframe",
                message=f"No candle data available for {sym} {tf}",
                status_code=404,
            )
        return _rows_to_candles(rows)

    latest = rows[-1].timestamp
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    stale_after_minutes = _TF_STALE_REFRESH_MINUTES.get(tf)
    stale_after = (
        timedelta(minutes=stale_after_minutes)
        if stale_after_minutes is not None
        else _STALE_AFTER
    )
    if now - latest > stale_after:
        logger.info(
            "candle_cache_stale symbol=%s timeframe=%s latest=%s stale_after_minutes=%s",
            sym,
            tf,
            latest.isoformat(),
            int(stale_after.total_seconds() / 60),
        )
        threading.Thread(target=_bg_refresh, args=(sym, tf), daemon=True).start()

    return _rows_to_candles(rows)


def refresh_all_symbols(
    symbols: list[str],
    timeframes: list[str],
    db: Session | None = None,
    *,
    recent_only: bool = False,
    recent_count: int = 500,
) -> None:
    """Refresh cache for every symbol×timeframe (worker count tuned by DB backend)."""
    _ = db  # unused — SQLite sessions are not shared across threads
    pairs = [(s.upper(), t.lower()) for s in symbols for t in timeframes]

    def _one(pair: tuple[str, str]) -> None:
        sym, tf = pair
        sess = SessionLocal()
        try:
            n = (
                refresh_candles_recent(sym, tf, sess, recent_count=recent_count)
                if recent_only
                else refresh_candles(sym, tf, sess)
            )
            logger.info("Cache refresh: %s %s — %s candles written", sym, tf, n)
        except Exception as e:
            logger.warning("Cache refresh failed: %s %s — %s", sym, tf, e)
        finally:
            sess.close()

    with ThreadPoolExecutor(max_workers=_CACHE_REFRESH_WORKERS) as ex:
        futures = [ex.submit(_one, p) for p in pairs]
        for f in as_completed(futures):
            f.result()


def get_cache_stats(db: Session) -> dict[str, Any]:
    total_rows = db.query(CandleCache).count()
    sym_count = db.query(func.count(func.distinct(CandleCache.symbol))).scalar() or 0
    tf_count = db.query(func.count(func.distinct(CandleCache.timeframe))).scalar() or 0
    row = db.query(func.min(CandleCache.timestamp), func.max(CandleCache.timestamp)).one()
    oldest, newest = row[0], row[1]
    size_mb = (total_rows * _BYTES_PER_ROW_ESTIMATE) / (1024 * 1024)
    return {
        "total_rows": total_rows,
        "symbols_covered": int(sym_count),
        "timeframes_covered": int(tf_count),
        "oldest_entry": oldest.isoformat() if oldest else None,
        "newest_entry": newest.isoformat() if newest else None,
        "estimated_size_mb": round(size_mb, 4),
    }
