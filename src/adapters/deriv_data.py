"""Deriv data adapter: fetch OHLC via Deriv WebSocket (read-only helpers).

This module provides a small helper to fetch historical OHLC/candles from
Deriv's WebSocket API and return `Candle` objects usable by the core feature
engine. Tests should monkeypatch `websocket.create_connection` to avoid
network calls.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import pathlib
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

import websocket
import yaml
from dateutil import parser as date_parser

from src.core.features import Candle, normalize_candles
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Interval → Deriv granularity (seconds) mapping
# ---------------------------------------------------------------------------
INTERVAL_TO_GRANULARITY: Dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}

_TF_WINDOWS_PATH = pathlib.Path(__file__).parent.parent.parent / "config" / "timeframe_windows.yaml"
_active_symbols_cache: set[str] | None = None


@dataclass
class DerivConfig:
	app_id: str
	api_token: str

	@classmethod
	def from_env(cls, app_id_var: str = "DERIV_APP_ID", token_var: str = "DERIV_API_TOKEN") -> "DerivConfig":
		app_id = os.getenv(app_id_var)
		api_token = os.getenv(token_var)
		if not app_id or not api_token:
			raise RuntimeError(
				f"Missing Deriv credentials: ensure {app_id_var} and {token_var} are set in the environment or .env."
			)
		return cls(app_id=app_id, api_token=api_token)


def _to_epoch_seconds(dt: Any) -> int:
	if isinstance(dt, (int, float)):
		return int(dt)
	if isinstance(dt, datetime):
		if dt.tzinfo is None:
			dt = dt.replace(tzinfo=timezone.utc)
		return int(dt.timestamp())
	parsed = date_parser.parse(str(dt))
	if parsed.tzinfo is None:
		parsed = parsed.replace(tzinfo=timezone.utc)
	return int(parsed.timestamp())


DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3?app_id={app_id}"
_MAX_DERIV_CANDLES_PER_REQUEST = 5000
_RETRYABLE_DERIV_ERROR_CODES = {"RateLimit"}

# Cap requested history for Deriv: synthetics often have shorter broker retention than YAML lookbacks.
DERIV_MAX_LOOKBACK_DAYS: dict[str, float] = {
    "5m": 30,
    "15m": 60,
    "30m": 90,
    "1h": 365,
    "4h": 730,
    "1d": 2190,
    "1w": 3650,
    "1mo": 7300,
}


def fetch_deriv_ohlc(
	symbol_code: str,
	granularity_sec: int,
	start: Any,
	end: Any,
	*,
	cfg: Optional[DerivConfig] = None,
) -> List[Candle]:
	"""Fetch OHLC candles from Deriv via WebSocket and return a list of Candle objects.

	- symbol_code: e.g. "R_10", "R_25".
	- granularity_sec: seconds per candle (e.g., 300, 900).
	- start, end: datetime/ISO string/epoch (inclusive window).
	- cfg: optional DerivConfig; if None, read from env using DerivConfig.from_env().
	"""
	if cfg is None:
		cfg = DerivConfig.from_env()

	start_epoch = _to_epoch_seconds(start)
	end_epoch = _to_epoch_seconds(end)
	if end_epoch <= start_epoch:
		raise ValueError("end must be strictly greater than start for Deriv OHLC fetch.")

	url = DERIV_WS_URL.format(app_id=cfg.app_id)
	ws = websocket.create_connection(url, timeout=30)

	try:
		# authorize
		auth_payload = {"authorize": cfg.api_token}
		ws.send(json.dumps(auth_payload))
		auth_resp = json.loads(ws.recv())
		if "error" in auth_resp:
			raise RuntimeError(f"Deriv authorization error: {auth_resp['error']}")

		def _request_candles_page(page_end_epoch: int) -> Optional[List[Dict[str, Any]]]:
			for attempt in range(1, 4):
				try:
					req = {
						"ticks_history": symbol_code,
						"style": "candles",
						"granularity": granularity_sec,
						"start": start_epoch,
						"end": page_end_epoch,
						"count": _MAX_DERIV_CANDLES_PER_REQUEST,
					}
					ws.send(json.dumps(req))
					while True:
						msg = json.loads(ws.recv())
						if "error" in msg:
							error_obj = msg["error"] or {}
							error_code = error_obj.get("code")
							logger.warning(
								"Deriv page error symbol=%s granularity=%s start=%s end=%s code=%s detail=%s",
								symbol_code,
								granularity_sec,
								start_epoch,
								page_end_epoch,
								error_code,
								error_obj,
							)
							if error_code in _RETRYABLE_DERIV_ERROR_CODES:
								raise RuntimeError(f"retryable_deriv_error:{error_code}")
							raise RuntimeError(f"Deriv OHLC error: {error_obj}")
						if "candles" in msg:
							return msg.get("candles", [])
				except (TimeoutError, websocket.WebSocketTimeoutException):
					if attempt < 3:
						time.sleep(1.0)
						continue
					logger.warning(
						"Deriv fetch timed out after 3 retries: %s %ss end=%s",
						symbol_code,
						granularity_sec,
						page_end_epoch,
					)
					return None
				except RuntimeError as e:
					if "retryable_deriv_error:RateLimit" in str(e):
						if attempt < 3:
							time.sleep(1.0)
							continue
						logger.warning(
							"Deriv fetch rate-limited after 3 retries: %s %ss end=%s",
							symbol_code,
							granularity_sec,
							page_end_epoch,
						)
						return None
					raise
				except Exception:
					raise
			return None

		by_epoch: Dict[int, Dict[str, Any]] = {}
		current_end = end_epoch
		while current_end > start_epoch:
			raw_candles = _request_candles_page(current_end)
			if raw_candles is None:
				break
			if not raw_candles:
				break

			for c in raw_candles:
				epoch = c.get("epoch")
				if epoch is None:
					continue
				by_epoch[int(epoch)] = {
					"epoch": epoch,
					"open": c.get("open"),
					"high": c.get("high"),
					"low": c.get("low"),
					"close": c.get("close"),
					"volume": c.get("volume", 0.0),
				}

			if len(raw_candles) < _MAX_DERIV_CANDLES_PER_REQUEST:
				break

			oldest_epoch = raw_candles[0].get("epoch")
			if oldest_epoch is None:
				break
			next_end = int(oldest_epoch) - 1
			if next_end <= start_epoch:
				break
			current_end = next_end
			time.sleep(0.2)

		if not by_epoch:
			return []

		rows = [by_epoch[e] for e in sorted(by_epoch.keys())]
		candles = normalize_candles(rows)
		return candles

	finally:
		try:
			ws.close()
		except Exception:
			pass


# ---------------------------------------------------------------------------
# Config helpers (mirrors binance_data pattern)
# ---------------------------------------------------------------------------

def _load_tf_config() -> Dict[str, Any]:
    """Load timeframe_windows.yaml."""
    try:
        with open(_TF_WINDOWS_PATH) as fh:
            return yaml.safe_load(fh) or {}
    except Exception as e:
        logger.warning("Failed to load %s: %s. Using defaults.", _TF_WINDOWS_PATH, e)
        return {}


def _get_lookback_days(interval: str) -> float:
    """Return lookback_days for *interval* from config, with sensible defaults."""
    cfg = _load_tf_config()
    tfs = cfg.get("timeframes", {})
    if interval in tfs and "lookback_days" in tfs[interval]:
        return float(tfs[interval]["lookback_days"])
    defaults: Dict[str, float] = {
        "1m": 1.5,
        "5m": 7.5,
        "15m": 25.0,
        "1h": 100.0,
        "4h": 365.0,
        "1d": 2190.0,
        "1w": 3650.0,
        "1mo": 7300.0,
    }
    return defaults.get(interval, 7.5)


# ---------------------------------------------------------------------------
# Active-symbols validation
# ---------------------------------------------------------------------------

def get_active_deriv_symbols(cfg: Optional[DerivConfig] = None) -> List[str]:
    """Return a list of active Deriv symbol codes from the active_symbols endpoint.

    For symbol discovery, only the app_id is required — the API token is
    optional.  Falls back to Deriv's public demo app_id (1089) when
    DERIV_APP_ID is not set so the function works without credentials.

    Returns an empty list (with a WARNING) on any error so callers can decide
    whether to proceed or abort.
    """
    if cfg is not None:
        app_id = cfg.app_id
        api_token: Optional[str] = cfg.api_token
    else:
        app_id = os.getenv("DERIV_APP_ID", "1089")
        api_token = os.getenv("DERIV_API_TOKEN")

    url = DERIV_WS_URL.format(app_id=app_id)
    try:
        ws = websocket.create_connection(url, timeout=10)
        try:
            # Authorize only when a token is available; active_symbols works
            # without authorization on the public app_id.
            if api_token:
                ws.send(json.dumps({"authorize": api_token}))
                auth_resp = json.loads(ws.recv())
                if "error" in auth_resp:
                    logger.warning(
                        "Deriv auth error when fetching active symbols: %s",
                        auth_resp["error"],
                    )
                    return []
            ws.send(json.dumps({"active_symbols": "brief", "product_type": "basic"}))
            resp = json.loads(ws.recv())
            if "error" in resp:
                logger.warning("Deriv active_symbols error: %s", resp["error"])
                return []
            return [s["symbol"] for s in resp.get("active_symbols", []) if "symbol" in s]
        finally:
            try:
                ws.close()
            except Exception:
                pass
    except Exception as e:
        logger.warning("Failed to fetch Deriv active symbols: %s", e)
        return []


def _get_active_symbols_cached() -> set[str]:
    """Return cached active symbols, hydrating once per process lifetime."""
    global _active_symbols_cache
    if _active_symbols_cache is None:
        logger.warning("Hydrating Deriv active symbols cache")
        _active_symbols_cache = set(get_active_deriv_symbols())
    return _active_symbols_cache


# ---------------------------------------------------------------------------
# High-level sync / async interface (mirrors binance_data.py)
# ---------------------------------------------------------------------------

def fetch_deriv_ohlc_sync(
    symbol: str,
    interval: str,
    start_time: Optional[datetime] = None,
    cfg: Optional[DerivConfig] = None,
    active_symbols: Optional[set[str]] = None,
    validate_active_symbol: bool = True,
) -> List[Candle]:
    """Fetch OHLC candles from Deriv with the same interface as the Binance adapter.

    Args:
        symbol: Deriv symbol code (e.g. ``"R_10"``).
        interval: Candle interval string (e.g. ``"1h"``).
                  Must be a key of :data:`INTERVAL_TO_GRANULARITY`.
        start_time: If provided, fetch forward from this UTC datetime.
                    If *None*, the full lookback window from config is used.
        cfg: :class:`DerivConfig` instance; loaded from env when *None*.

    Returns:
        List of :class:`~src.core.features.Candle` objects sorted ascending
        by timestamp.

    Raises:
        ValueError: If *interval* is not in :data:`INTERVAL_TO_GRANULARITY`.
    """
    if interval in {"1w", "1mo"}:
        logger.info("Deriv resample request symbol=%s interval=%s source=1d", symbol, interval)
        lookback_days = _get_lookback_days(interval)
        max_deriv_days = DERIV_MAX_LOOKBACK_DAYS.get(interval, lookback_days)
        lookback_days = min(lookback_days, max_deriv_days)
        now = datetime.now(timezone.utc)
        start_dt = (
            start_time
            if start_time is not None
            else datetime.fromtimestamp(now.timestamp() - lookback_days * 86400, tz=timezone.utc)
        )
        daily = fetch_deriv_ohlc_sync(
            symbol,
            "1d",
            start_time=start_dt,
            cfg=cfg,
            active_symbols=active_symbols,
            validate_active_symbol=validate_active_symbol,
        )
        bucket_days = 7 if interval == "1w" else 30
        resampled = _resample_daily_candles(daily, bucket_days)
        logger.info(
            "Deriv resample completed symbol=%s interval=%s daily_count=%s resampled_count=%s",
            symbol,
            interval,
            len(daily),
            len(resampled),
        )
        return resampled

    if interval not in INTERVAL_TO_GRANULARITY:
        raise ValueError(
            f"Unsupported interval '{interval}'. "
            f"Supported: {list(INTERVAL_TO_GRANULARITY.keys()) + ['1w', '1mo']}"
        )

    if cfg is None:
        cfg = DerivConfig.from_env()

    # Symbol validation: only warn (do not crash) when active list is non-empty
    # and the symbol is absent. Callers can provide a cached active-symbol set
    # to avoid re-fetching the list for every symbol in a scan.
    if validate_active_symbol:
        active = active_symbols if active_symbols is not None else _get_active_symbols_cached()
        if active and symbol not in active:
            logger.debug(
                "Symbol '%s' not found in Deriv active symbols. Returning empty list.",
                symbol,
            )
            return []

    granularity = INTERVAL_TO_GRANULARITY[interval]
    lookback_days = _get_lookback_days(interval)
    max_deriv_days = DERIV_MAX_LOOKBACK_DAYS.get(interval, lookback_days)
    lookback_days = min(lookback_days, max_deriv_days)

    now = datetime.now(timezone.utc)
    if start_time is not None:
        start_dt = (
            start_time
            if start_time.tzinfo is not None
            else start_time.replace(tzinfo=timezone.utc)
        )
    else:
        start_dt = datetime.fromtimestamp(
            now.timestamp() - lookback_days * 86400,
            tz=timezone.utc,
        )

    candles = fetch_deriv_ohlc(symbol, granularity, start_dt, now, cfg=cfg)

    # Warn if history depth is shallower than the requested lookback window, but
    # still return whatever candles were obtained — never crash.
    expected_count = math.ceil(lookback_days * 86400 / granularity)
    if len(candles) < expected_count:
        logger.warning(
            "Deriv history for '%s' %s is shallower than expected: "
            "got %d candles, expected ~%d (lookback_days=%.1f). "
            "Returning available candles.",
            symbol,
            interval,
            len(candles),
            expected_count,
            lookback_days,
        )

    return candles


def fetch_deriv_account_balance(
    token: str,
    *,
    app_id: str | None = None,
) -> Dict[str, Any]:
    """Authorize and fetch Deriv account balance via WebSocket API."""
    effective_app_id = app_id or os.getenv("DERIV_APP_ID", "1089")
    ws = websocket.create_connection(
        DERIV_WS_URL.format(app_id=effective_app_id),
        timeout=15,
    )
    try:
        ws.send(json.dumps({"authorize": token}))
        auth_resp = json.loads(ws.recv())
        if "error" in auth_resp:
            raise RuntimeError(f"Deriv authorization error: {auth_resp['error']}")

        ws.send(json.dumps({"balance": 1}))
        bal_resp = json.loads(ws.recv())
        if "error" in bal_resp:
            raise RuntimeError(f"Deriv balance error: {bal_resp['error']}")
        if "balance" not in bal_resp:
            raise RuntimeError("Deriv balance response missing balance object")
        return bal_resp
    finally:
        try:
            ws.close()
        except Exception:
            pass


async def fetch_deriv_ohlc_async(
    symbol: str,
    interval: str,
    start_time: Optional[datetime] = None,
    cfg: Optional[DerivConfig] = None,
) -> List[Candle]:
    """Async interface for :func:`fetch_deriv_ohlc_sync`.

    Runs the synchronous WebSocket fetch in a thread-pool executor so it does
    not block the event loop.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: fetch_deriv_ohlc_sync(symbol, interval, start_time=start_time, cfg=cfg),
    )


def _resample_daily_candles(candles: List[Candle], bucket_days: int) -> List[Candle]:
    if not candles:
        return []
    ordered = sorted(candles, key=lambda c: c.timestamp)
    out: List[Candle] = []
    bucket: List[Candle] = []
    for candle in ordered:
        bucket.append(candle)
        if len(bucket) >= bucket_days:
            out.append(
                Candle(
                    timestamp=bucket[0].timestamp,
                    open=bucket[0].open,
                    high=max(c.high for c in bucket),
                    low=min(c.low for c in bucket),
                    close=bucket[-1].close,
                    volume=sum(float(c.volume) for c in bucket),
                )
            )
            bucket = []
    if bucket:
        out.append(
            Candle(
                timestamp=bucket[0].timestamp,
                open=bucket[0].open,
                high=max(c.high for c in bucket),
                low=min(c.low for c in bucket),
                close=bucket[-1].close,
                volume=sum(float(c.volume) for c in bucket),
            )
        )
    return out

