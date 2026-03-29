from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.adapters.binance_data import fetch_binance_ohlc_sync
from src.adapters.deriv_data import fetch_deriv_ohlc_sync
from src.core.structural_walker import serialize_state_report, walk_structure
from src.core.features import compute_ema
from src.core.trend_id import compute_internal_structure, identify_trend
from src.db.models import MonitoredSetup
from src.db.session import SessionLocal, get_db
from src.scanner.universe import compute_correlation_groups

logger = logging.getLogger(__name__)

_TF_WINDOWS_PATH = Path(__file__).parent.parent.parent.parent / "config" / "timeframe_windows.yaml"
with _TF_WINDOWS_PATH.open() as _f:
    _TF_WINDOWS: dict[str, Any] = yaml.safe_load(_f)

_SYMBOLS_PATH = Path(__file__).parent.parent.parent.parent / "config" / "symbols.yaml"
with _SYMBOLS_PATH.open() as _sf:
    _SYMBOLS_DATA: dict[str, Any] = yaml.safe_load(_sf)

_SYMBOL_CATEGORY_MAP: dict[str, str] = {}
for _name, _code in (_SYMBOLS_DATA.get("deriv") or {}).items():
    _name_lower = _name.lower()
    if any(kw in _name_lower for kw in [
        "volatility", "boom", "crash", "step", "jump",
        "range break", "rd bear", "rd bull", "wall street",
        "crypto", "otc", "index", "indices"
    ]):
        _sym_cat = "synthetic"
    elif any(kw in _name_lower for kw in ["gold", "silver", "oil", "brent", "copper", "palladium", "platinum"]):
        _sym_cat = "commodity"
    else:
        _sym_cat = "forex"
    _SYMBOL_CATEGORY_MAP[str(_code).upper()] = _sym_cat

FILTER_CONFIG: dict[str, Any] = {
    "use_parent_relative_filter": True,
    "min_impulse_parent_ratio": 0.15,
    "use_momentum_filter": True,
    "min_momentum_ratio": 0.5,
    "use_dominance_filter": True,
    "min_dominance_ratio": 1.5,
}

MTF_LADDER: dict[str, list[str]] = {
    "1h": ["4h", "1d"],
    "4h": ["1d"],
    "15m": ["1h", "4h"],
    "5m": ["15m", "1h"],
}

BASE_FETCH_TIMEFRAME = "15m"
MAX_DERIV_WORKERS = 5

RESAMPLE_MINUTES = {
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


def _resample_candles(candles: list, target_minutes: int) -> list:
    """
    Resample a list of Candle objects into a higher timeframe.
    candles must be sorted oldest-first.
    target_minutes must be a multiple of the source candle interval.
    Returns a new list of Candle-like dicts with keys:
    timestamp, open, high, low, close, volume.
    """
    if not candles:
        return []

    from src.adapters.binance_data import Candle

    result = []
    bucket: list = []
    for candle in candles:
        bucket.append(candle)
        total_minutes = len(bucket) * 15
        if total_minutes >= target_minutes:
            result.append(
                Candle(
                    timestamp=bucket[0].timestamp,
                    open=bucket[0].open,
                    high=max(c.high for c in bucket),
                    low=min(c.low for c in bucket),
                    close=bucket[-1].close,
                    volume=sum(getattr(c, "volume", 0) for c in bucket),
                )
            )
            bucket = []
    return result


router = APIRouter(prefix="/api/setups", tags=["setups"])

_scan_status = {
    "in_progress": False,
    "stage": None,
    "total_symbols": 0,
    "stage1_complete": 0,
    "stage2_complete": 0,
    "stage2_total": 0,
    "started_at": None,
    "completed_at": None,
}

_COMMODITIES_SYMBOLS = {"XAUUSD", "XAGUSD", "USOIL", "UKOIL", "NGAS"}
_INDICES_SYMBOLS = {"NAS100", "SPX500", "GER40", "UK100", "JP225"}
DERIV_SYNTHETIC_PREFIXES = (
    "R_",
    "1HZ",
    "BOOM",
    "CRASH",
    "JD",
    "RB",
    "RDBEAR",
    "RDBULL",
    "stpRNG",
    "OTC_",
    "WLD",
    "cry",
)


class ScanRequest(BaseModel):
    symbols: list[str] = []
    timeframe: str = "1h"


def _parse_structural_state(raw_value: Any) -> dict[str, Any]:
    if raw_value is None:
        return {}
    if isinstance(raw_value, dict):
        return raw_value
    if isinstance(raw_value, str):
        parsed = json.loads(raw_value)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("structural_state_json must be a dict-compatible value")


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _serialize_setup(setup: MonitoredSetup) -> dict[str, Any]:
    """Serialize a MonitoredSetup to a frontend-ready dict.

    Parses structural_state_json to extract pullback_depth,
    total_mitigation_count, waiting_for, and active_choch_zone
    as flat top-level fields so the frontend does not need to
    parse nested JSON.
    """
    state: dict[str, Any] = {}
    if setup.structural_state_json:
        try:
            state = (
                setup.structural_state_json
                if isinstance(setup.structural_state_json, dict)
                else json.loads(setup.structural_state_json)
            )
        except Exception:
            state = {}

    pullback_depth = state.get("max_depth_reached", 0)
    total_mitigation_count = state.get("total_mitigation_count", 0)
    waiting_for = state.get("waiting_for", "")
    global_trend = state.get("global_trend", setup.htf_trend_direction or "range")

    active_choch_zone = None
    active_bos = None
    levels = state.get("levels", [])
    if levels:
        deepest = levels[-1]
        choch = deepest.get("choch_zone")
        if choch:
            active_choch_zone = {
                "lower_boundary": choch.get("lower_boundary"),
                "upper_boundary": choch.get("upper_boundary"),
            }
        struct = deepest.get("structural_level")
        if struct:
            active_bos = {
                "price": struct.get("price"),
                "break_type": (
                    deepest.get("crossing_attempt", {}).get("break_type", "broken")
                    if deepest.get("crossing_attempt")
                    else "broken"
                ),
            }

    mtf_alignment = setup.mtf_alignment or (
        {setup.htf_timeframe: setup.htf_trend_direction or "range"}
        if setup.htf_timeframe
        else {}
    )

    active_zones = []
    if hasattr(setup, "alert_zones") and setup.alert_zones:
        active_zones = [
            {
                "zone_type": zone.zone_type,
                "price_high": zone.price_high,
                "price_low": zone.price_low,
                "is_manual_override": zone.is_manual_override,
            }
            for zone in setup.alert_zones
            if zone.is_active
        ]

    return {
        "setup_id": setup.id,
        "symbol": setup.symbol,
        "broker": _derive_broker(setup.symbol),
        "category": _infer_category(setup.symbol),
        "timeframe": setup.htf_timeframe,
        "trend": global_trend,
        "current_phase": setup.current_phase or _infer_phase(state),
        "fsm_state": setup.status or "SCANNING",
        "ema_signal": setup.ema_signal or "WAITING",
        "trend_score": float(setup.trend_score or 0),
        "pullback_depth": pullback_depth,
        "total_mitigation_count": total_mitigation_count,
        "waiting_for": waiting_for,
        "active_choch_zone": active_choch_zone,
        "active_bos": active_bos,
        "active_zones": active_zones,
        "mtf_alignment": mtf_alignment,
        "structural_state": state,
        "structural_state_json": state,
        "last_checked_at": setup.last_checked_at.isoformat() if setup.last_checked_at else None,
        "created_at": setup.created_at.isoformat() if setup.created_at else None,
    }


def _infer_category(symbol: str) -> str:
    """Infer asset category from symbol name."""
    symbol_upper = symbol.upper()
    if symbol_upper in _SYMBOL_CATEGORY_MAP:
        return _SYMBOL_CATEGORY_MAP[symbol_upper]
    if any(token in symbol_upper for token in ["USDT", "BTC", "ETH", "BNB", "SOL", "XRP"]):
        return "crypto"
    if any(
        token in symbol_upper
        for token in [
            "XAU",
            "XAG",
            "OILUSD",
            "OIL",
            "BRENT",
            "FRXOILUSD",
            "FRXXPDUSD",
            "FRXXPTUSD",
            "XPDUSD",
            "XPTUSD",
        ]
    ):
        return "commodity"
    SYNTHETIC_PATTERNS = (
        "R_", "1HZ", "BOOM", "CRASH", "JD", "RB",
        "RDBEAR", "RDBULL", "stpRNG", "OTC_", "WLD",
        "cry", "STEP", "RANGE", "JUMP",
    )
    if any(symbol_upper.startswith(p.upper()) for p in SYNTHETIC_PATTERNS):
        return "synthetic"
    if symbol_upper.startswith("FRX"):
        return "forex"
    if len(symbol_upper) == 6 and symbol_upper.isalpha():
        return "forex"
    return "unknown"


def _infer_phase(state: dict[str, Any]) -> str:
    """Infer current market phase from structural state."""
    if not state:
        return "unknown"
    levels = state.get("levels", [])
    if not levels:
        return "unknown"
    if state.get("walkable"):
        return "retracement"
    return "impulse"


def _has_active_choch_zone(setup: MonitoredSetup) -> bool:
    """Check if setup has an active CHoCH zone in its structural state."""
    if not setup.structural_state_json:
        return False
    levels = setup.structural_state_json.get("levels", [])
    for level in levels:
        choch = level.get("choch_zone")
        if choch:
            return True
    return False


def _has_manual_override_zone(setup: MonitoredSetup) -> bool:
    """Check if setup has an active manual override zone."""
    for zone in setup.alert_zones:
        if zone.is_manual_override and zone.is_active:
            return True
    return False


def _derive_category(symbol: str) -> str:
    normalized = symbol.upper()
    if normalized.endswith("USDT") or normalized.endswith("BTC"):
        return "CRYPTO"
    if normalized in _COMMODITIES_SYMBOLS:
        return "COMMODITIES"
    if normalized in _INDICES_SYMBOLS:
        return "INDICES"
    if normalized.startswith("V") or normalized.startswith("BOOM") or normalized.startswith("CRASH"):
        return "SYNTHETIC"
    return "FOREX"


def _derive_broker(symbol: str) -> str:
    normalized = symbol.upper()
    if normalized.endswith("USDT") or normalized.endswith("BTC"):
        return "binance"
    return "deriv"


def _serialize_summary(setup: MonitoredSetup) -> dict[str, Any]:
    return {
        "symbol": setup.symbol,
        "broker": _derive_broker(setup.symbol),
        "timeframe": setup.htf_timeframe,
        "trend": setup.htf_trend_direction,
        "fsm_state": setup.status,
        "trend_score": setup.trend_score,
        "category": _derive_category(setup.symbol),
    }


def _get_setup_by_symbol(db: Session, symbol: str) -> MonitoredSetup | None:
    return (
        db.query(MonitoredSetup)
        .filter(MonitoredSetup.symbol == symbol)
        .order_by(MonitoredSetup.trend_score.desc(), MonitoredSetup.id.asc())
        .first()
    )


def _write_stage1_result(symbol: str, data: dict[str, Any], timeframe: str, db: Session) -> None:
    """Persist one Stage 1 scan result into monitored_setups."""
    result = data["result"]
    mtf_alignment = data.get("mtf_alignment") or {timeframe: result.get("trend", "unknown")}
    existing = (
        db.query(MonitoredSetup)
        .filter(
            MonitoredSetup.symbol == symbol,
            MonitoredSetup.htf_timeframe == timeframe,
        )
        .one_or_none()
    )

    trend_score = 0.0
    now = datetime.now(timezone.utc)
    status = "MONITORING" if result.get("current_phase") == "retracement" else "SCANNING"

    if existing is not None:
        existing.htf_trend_direction = result["trend"]
        existing.current_phase = result.get("current_phase")
        existing.mtf_alignment = mtf_alignment
        existing.status = status
        existing.trend_score = trend_score
        existing.last_checked_at = now
        existing.updated_at = now
    else:
        db.add(
            MonitoredSetup(
                symbol=symbol,
                htf_timeframe=timeframe,
                htf_trend_direction=result["trend"],
                current_phase=result.get("current_phase"),
                status=status,
                trend_score=trend_score,
                structural_state_json={},
                mtf_alignment=mtf_alignment,
                last_checked_at=now,
                created_at=now,
                updated_at=now,
            )
        )
    db.commit()
    _evict_to_capacity(db, capacity=50)


def _process_deriv_symbol(
    symbol: str,
    timeframe: str,
    filter_config: dict[str, Any],
    start_time: datetime,
    active_symbols: set[str] | None,
) -> tuple[str, dict[str, Any] | None]:
    """Process one Deriv symbol for Stage 1."""
    try:
        candles = fetch_deriv_ohlc_sync(
            symbol,
            timeframe,
            start_time=start_time,
            active_symbols=active_symbols,
        )
        if not candles:
            return symbol, None

        result = identify_trend(candles, **filter_config)
        compute_internal_structure(candles, result["legs"], **filter_config)
        return symbol, {"candles": candles, "result": result}
    except Exception as e:  # noqa: BLE001
        logger.warning("Deriv Stage 1 failed for %s: %s", symbol, e)
        return symbol, None


def _estimate_total_symbols(request: ScanRequest) -> int:
    if request.symbols:
        return len(request.symbols)
    deriv_symbols = {
        str(code).upper()
        for code in (_SYMBOLS_DATA.get("deriv") or {}).values()
    }
    return 50 + len(deriv_symbols | _COMMODITIES_SYMBOLS | _INDICES_SYMBOLS)


def _evict_to_capacity(db: Session, capacity: int = 50) -> None:
    rows = db.execute(
        text(
            """
            SELECT ms.id, ms.symbol, ms.trend_score,
                   CASE
                       WHEN EXISTS (
                           SELECT 1
                           FROM alert_zones az
                           WHERE az.setup_id = ms.id
                             AND az.is_manual_override = 1
                             AND az.is_active = 1
                       )
                       THEN 1
                       ELSE 0
                   END AS is_protected
            FROM monitored_setups ms
            ORDER BY ms.trend_score DESC, ms.id ASC
            """
        )
    ).mappings().all()
    if len(rows) <= capacity:
        return

    to_evict_ids: list[int] = []
    for row in rows[capacity:]:
        if not bool(row["is_protected"]):
            to_evict_ids.append(int(row["id"]))

    if not to_evict_ids:
        return

    evicted = (
        db.query(MonitoredSetup)
        .filter(MonitoredSetup.id.in_(to_evict_ids))
        .all()
    )
    for setup in evicted:
        logger.info(
            "Stage 3: Evicting low scorer %s (score=%.1f) — capacity exceeded",
            setup.symbol,
            setup.trend_score,
        )
        db.delete(setup)
    db.commit()


def _run_scan_sync(request: ScanRequest) -> None:
    db = SessionLocal()
    try:
        _evict_to_capacity(db, capacity=50)

        symbols = request.symbols
        deriv_active_symbols: set[str] | None = None

        # Auto-discover universe if no symbols provided
        if not symbols:
            discovered: list[str] = []

            # Top 50 Binance crypto by volume
            try:
                from src.scanner.market_scanner import fetch_top_symbols

                binance_symbols = fetch_top_symbols(n=50)
                discovered.extend(binance_symbols)
                logger.info("Discovered %d Binance symbols", len(binance_symbols))
            except Exception as e:  # noqa: BLE001
                logger.warning("Binance universe discovery failed: %s", e)

            # All active Deriv symbols, always extended with hardcoded forex/commodity/indices
            try:
                from src.adapters.deriv_data import get_active_deriv_symbols
                from src.scanner.market_scanner import (
                    DERIV_COMMODITY_SYMBOLS,
                    DERIV_FOREX_SYMBOLS,
                    DERIV_INDICES_SYMBOLS,
                )

                deriv_active_symbols = set(get_active_deriv_symbols())
                deriv_symbols = sorted(
                    deriv_active_symbols
                    | set(DERIV_FOREX_SYMBOLS)
                    | set(DERIV_COMMODITY_SYMBOLS)
                    | set(DERIV_INDICES_SYMBOLS)
                )
                discovered.extend(deriv_symbols)
                logger.info(
                    "Discovered %d Deriv symbols (including hardcoded forex/commodity/indices)",
                    len(deriv_symbols),
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("Deriv universe discovery failed: %s", e)

            seen = set()
            symbols = []
            for symbol in discovered:
                if symbol not in seen:
                    seen.add(symbol)
                    symbols.append(symbol)

            if not symbols:
                raise RuntimeError("Universe discovery failed — no symbols found from Binance or Deriv")

            logger.info("Full universe: %d symbols to scan", len(symbols))

        _scan_status["in_progress"] = True
        _scan_status["stage"] = "stage1"
        _scan_status["total_symbols"] = len(symbols)
        _scan_status["stage1_complete"] = 0
        _scan_status["stage2_complete"] = 0
        _scan_status["stage2_total"] = 0
        _scan_status["started_at"] = datetime.now(timezone.utc).isoformat()
        _scan_status["completed_at"] = None

        stage1_results: dict[str, dict[str, Any]] = {}
        base_tf_config = _TF_WINDOWS.get("timeframes", {}).get(BASE_FETCH_TIMEFRAME, {})
        base_lookback_days: float = base_tf_config.get("lookback_days", 7.5)
        base_start_time = datetime.now(timezone.utc) - timedelta(days=base_lookback_days)

        binance_symbols = [
            s for s in symbols if s.upper().endswith("USDT") or s.upper().endswith("BTC")
        ]
        deriv_symbols = [
            s for s in symbols if not (s.upper().endswith("USDT") or s.upper().endswith("BTC"))
        ]

        for symbol in binance_symbols:
            try:
                base_candles = fetch_binance_ohlc_sync(
                    symbol,
                    BASE_FETCH_TIMEFRAME,
                    start_time=base_start_time,
                )
                if not base_candles:
                    continue

                base_result = identify_trend(base_candles, **FILTER_CONFIG)

                mtf_alignment: dict[str, str] = {}
                if base_result.get("trend") in ("up", "down"):
                    mtf_alignment[BASE_FETCH_TIMEFRAME] = base_result.get("trend", "unknown")
                for tf in ["30m", "1h", "4h", "1d"]:
                    target_minutes = RESAMPLE_MINUTES[tf]
                    try:
                        tf_candles = _resample_candles(base_candles, target_minutes)
                        if not tf_candles:
                            continue
                        tf_result = identify_trend(tf_candles, **FILTER_CONFIG)
                        tf_trend = tf_result.get("trend", "unknown")
                        if tf_trend in ("up", "down"):
                            mtf_alignment[tf] = tf_trend
                    except Exception:
                        continue

                requested_minutes = RESAMPLE_MINUTES.get(request.timeframe)
                if requested_minutes is None:
                    primary_candles = fetch_binance_ohlc_sync(
                        symbol,
                        request.timeframe,
                        start_time=base_start_time,
                    )
                elif request.timeframe == BASE_FETCH_TIMEFRAME:
                    primary_candles = base_candles
                else:
                    primary_candles = _resample_candles(base_candles, requested_minutes)

                if len(primary_candles) < 50:
                    try:
                        primary_candles = fetch_binance_ohlc_sync(
                            symbol,
                            request.timeframe,
                            start_time=base_start_time,
                        )
                    except Exception:
                        pass

                if not primary_candles:
                    continue

                result = identify_trend(primary_candles, **FILTER_CONFIG)
                compute_internal_structure(primary_candles, result["legs"], **FILTER_CONFIG)
                stage1_results[symbol] = {
                    "candles": primary_candles,
                    "result": result,
                    "mtf_alignment": mtf_alignment,
                }

                _write_stage1_result(symbol, stage1_results[symbol], request.timeframe, db)
                _scan_status["stage1_complete"] += 1
                logger.info(
                    "Stage 1 complete: %s trend=%s phase=%s",
                    symbol,
                    result.get("trend"),
                    result.get("current_phase"),
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("Stage 1 failed for %s: %s", symbol, e)
                continue

        if deriv_symbols:
            tf_config = _TF_WINDOWS.get("timeframes", {}).get(request.timeframe, {})
            lookback_days: float = tf_config.get("lookback_days", 100.0)
            deriv_start_time = datetime.now(timezone.utc) - timedelta(days=lookback_days)
            deriv_started = datetime.now(timezone.utc)
            logger.warning(
                "Stage 1 Deriv concurrent start: symbols=%d max_workers=%d elapsed=0.00s",
                len(deriv_symbols),
                MAX_DERIV_WORKERS,
            )

            with ThreadPoolExecutor(max_workers=MAX_DERIV_WORKERS) as executor:
                futures = {
                    executor.submit(
                        _process_deriv_symbol,
                        sym,
                        request.timeframe,
                        FILTER_CONFIG,
                        deriv_start_time,
                        deriv_active_symbols,
                    ): sym
                    for sym in deriv_symbols
                }

                for future in as_completed(futures):
                    symbol = futures[future]
                    try:
                        resolved_symbol, data = future.result()
                    except Exception as e:  # noqa: BLE001
                        logger.warning("Deriv Stage 1 future failed for %s: %s", symbol, e)
                        continue

                    if data is None:
                        continue

                    stage1_results[resolved_symbol] = data
                    _write_stage1_result(resolved_symbol, data, request.timeframe, db)
                    _scan_status["stage1_complete"] += 1

            deriv_elapsed = (datetime.now(timezone.utc) - deriv_started).total_seconds()
            logger.warning(
                "Stage 1 Deriv concurrent done: symbols=%d elapsed=%.2fs",
                len(deriv_symbols),
                deriv_elapsed,
            )

        _scan_status["stage"] = "stage2"
        retracement_symbols = [
            sym
            for sym, data in stage1_results.items()
            if data["result"].get("current_phase") == "retracement"
        ]
        _scan_status["stage2_total"] = len(retracement_symbols)
        logger.info(
            "Stage 2: %d retracement markets to analyze deeply",
            len(retracement_symbols),
        )

        for symbol in retracement_symbols:
            try:
                data = stage1_results[symbol]
                candles = data["candles"]
                result = data["result"]

                state_report = walk_structure(
                    candles,
                    result,
                    FILTER_CONFIG,
                    max_depth=3,
                    binance_symbol=symbol,
                )
                serialized = serialize_state_report(state_report)
                depth = serialized.get("max_depth_reached", 0)
                mitigations = serialized.get("total_mitigation_count", 0)
                trend_score = float((depth * 10) + (mitigations * 5))

                ema_signal = "WAITING"
                ema_fast = compute_ema(candles, 9)
                ema_slow = compute_ema(candles, 21)

                crossover: str | None = None
                for idx in range(max(1, len(candles) - 2), len(candles)):
                    prev_fast = ema_fast[idx - 1]
                    prev_slow = ema_slow[idx - 1]
                    curr_fast = ema_fast[idx]
                    curr_slow = ema_slow[idx]
                    if None in (prev_fast, prev_slow, curr_fast, curr_slow):
                        continue
                    if prev_fast <= prev_slow and curr_fast > curr_slow:
                        crossover = "up"
                    elif prev_fast >= prev_slow and curr_fast < curr_slow:
                        crossover = "down"

                has_structural_depth = int(serialized.get("max_depth_reached", 0) or 0) >= 1
                has_global_choch_zone = serialized.get("global_choch_zone") is not None
                if has_structural_depth and has_global_choch_zone:
                    if crossover == "up" and result.get("trend") == "up":
                        ema_signal = "LONG"
                    elif crossover == "down" and result.get("trend") == "down":
                        ema_signal = "SHORT"

                existing = (
                    db.query(MonitoredSetup)
                    .filter(
                        MonitoredSetup.symbol == symbol,
                        MonitoredSetup.htf_timeframe == request.timeframe,
                    )
                    .one_or_none()
                )
                current_time = datetime.now(timezone.utc)
                if existing is not None:
                    existing.structural_state_json = serialized
                    existing.trend_score = trend_score
                    existing.ema_signal = ema_signal
                    existing.updated_at = current_time
                else:
                    existing = MonitoredSetup(
                        symbol=symbol,
                        htf_timeframe=request.timeframe,
                        htf_trend_direction=result["trend"],
                        current_phase=result.get("current_phase"),
                        status="MONITORING",
                        ema_signal=ema_signal,
                        trend_score=trend_score,
                        structural_state_json=serialized,
                        mtf_alignment=data.get("mtf_alignment") or {request.timeframe: result.get("trend", "unknown")},
                        last_checked_at=current_time,
                        created_at=current_time,
                        updated_at=current_time,
                    )
                    db.add(existing)
                db.commit()
                _evict_to_capacity(db, capacity=50)

                _scan_status["stage2_complete"] += 1
                logger.info(
                    "Stage 2 complete: %s depth=%s mitigations=%s score=%s",
                    symbol,
                    depth,
                    mitigations,
                    trend_score,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("Stage 2 failed for %s: %s", symbol, e)
                continue

        if binance_symbols:
            _scan_status["stage"] = "stage2_catchup"
            catchup_candidates = (
                db.query(MonitoredSetup)
                .filter(
                    MonitoredSetup.status == "MONITORING",
                    MonitoredSetup.trend_score == 0.0,
                )
                .all()
            )
            binance_catchup = [
                setup
                for setup in catchup_candidates
                if (setup.symbol.upper().endswith("USDT") or setup.symbol.upper().endswith("BTC"))
                and not setup.structural_state_json
            ][:20]

            logger.info(
                "Stage 2 catch-up: %d Binance MONITORING markets with score=0 to process",
                len(binance_catchup),
            )

            for setup in binance_catchup:
                try:
                    tf_cfg = _TF_WINDOWS.get("timeframes", {}).get(setup.htf_timeframe, {})
                    cu_lookback: float = tf_cfg.get("lookback_days", 7.5)
                    cu_start = datetime.now(timezone.utc) - timedelta(days=cu_lookback)
                    cu_candles = fetch_binance_ohlc_sync(
                        setup.symbol, setup.htf_timeframe, start_time=cu_start
                    )
                    if not cu_candles:
                        continue

                    cu_result = identify_trend(cu_candles, **FILTER_CONFIG)
                    compute_internal_structure(cu_candles, cu_result["legs"], **FILTER_CONFIG)

                    if cu_result.get("current_phase") != "retracement":
                        setup.status = "SCANNING"
                        setup.current_phase = cu_result.get("current_phase")
                        setup.htf_trend_direction = cu_result["trend"]
                        setup.updated_at = datetime.now(timezone.utc)
                        db.commit()
                        continue

                    cu_state_report = walk_structure(
                        cu_candles,
                        cu_result,
                        FILTER_CONFIG,
                        max_depth=3,
                        binance_symbol=setup.symbol,
                    )
                    cu_serialized = serialize_state_report(cu_state_report)
                    cu_depth = cu_serialized.get("max_depth_reached", 0)
                    cu_mitigations = cu_serialized.get("total_mitigation_count", 0)
                    cu_score = float((cu_depth * 10) + (cu_mitigations * 5))

                    cu_ema_signal = "WAITING"
                    cu_ema_fast = compute_ema(cu_candles, 9)
                    cu_ema_slow = compute_ema(cu_candles, 21)
                    cu_crossover: str | None = None
                    for idx in range(max(1, len(cu_candles) - 2), len(cu_candles)):
                        pf = cu_ema_fast[idx - 1]
                        ps = cu_ema_slow[idx - 1]
                        cf = cu_ema_fast[idx]
                        cs = cu_ema_slow[idx]
                        if None in (pf, ps, cf, cs):
                            continue
                        if pf <= ps and cf > cs:
                            cu_crossover = "up"
                        elif pf >= ps and cf < cs:
                            cu_crossover = "down"

                    cu_has_depth = int(cu_serialized.get("max_depth_reached", 0) or 0) >= 1
                    cu_has_choch = cu_serialized.get("global_choch_zone") is not None
                    if cu_has_depth and cu_has_choch:
                        if cu_crossover == "up" and cu_result.get("trend") == "up":
                            cu_ema_signal = "LONG"
                        elif cu_crossover == "down" and cu_result.get("trend") == "down":
                            cu_ema_signal = "SHORT"

                    setup.structural_state_json = cu_serialized
                    setup.trend_score = cu_score
                    setup.ema_signal = cu_ema_signal
                    setup.htf_trend_direction = cu_result["trend"]
                    setup.current_phase = cu_result.get("current_phase")
                    setup.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    logger.info("Stage 2 catch-up: %s score=%.1f", setup.symbol, cu_score)
                except Exception as e:  # noqa: BLE001
                    logger.warning("Stage 2 catch-up failed for %s: %s", setup.symbol, e)
                    continue

        try:
            _scan_status["stage"] = "stage3_correlation"

            all_setups = (
                db.query(MonitoredSetup)
                .order_by(MonitoredSetup.trend_score.desc(), MonitoredSetup.id.asc())
                .all()
            )

            if all_setups and stage1_results:
                scan_data = []
                for setup in all_setups:
                    scan_data.append({
                        "symbol": setup.symbol,
                        "interval": setup.htf_timeframe,
                        "trend": setup.htf_trend_direction,
                        "trend_score": setup.trend_score,
                    })
                scan_df = pd.DataFrame(scan_data)

                symbol_candle_map = {}
                for symbol, data in stage1_results.items():
                    symbol_candle_map[(symbol, request.timeframe)] = data["candles"]

                filtered_df = compute_correlation_groups(scan_df, symbol_candle_map)
                filtered_symbols = set(filtered_df["symbol"].tolist())

                for setup in all_setups:
                    if setup.symbol not in filtered_symbols:
                        if not _has_manual_override_zone(setup) and not _has_active_choch_zone(setup):
                            logger.info(
                                "Stage 3: Removing correlated duplicate %s (score=%.1f)",
                                setup.symbol,
                                setup.trend_score,
                            )
                            db.delete(setup)
                db.commit()
            else:
                logger.info(
                    "Stage 3 correlation filter skipped: no Stage 1 candle set available for this scan"
                )

            _scan_status["stage"] = "stage3_eviction"
            _evict_to_capacity(db, capacity=50)
            _scan_status["stage"] = "complete"
        except Exception as e:  # noqa: BLE001
            logger.warning("Stage 3 correlation/eviction failed: %s", e)
            _scan_status["stage"] = "failed"
    except Exception as e:  # noqa: BLE001
        logger.exception("Background scan failed: %s", e)
        _scan_status["stage"] = "failed"
    finally:
        _scan_status["in_progress"] = False
        _scan_status["completed_at"] = datetime.now(timezone.utc).isoformat()
        db.close()


@router.get("")
def list_setups(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    setups = (
        db.query(MonitoredSetup)
        .order_by(MonitoredSetup.trend_score.desc(), MonitoredSetup.id.asc())
        .all()
    )
    return [_serialize_setup(setup) for setup in setups]


@router.get("/summary")
def list_setups_summary(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    setups = (
        db.query(MonitoredSetup)
        .order_by(MonitoredSetup.trend_score.desc(), MonitoredSetup.id.asc())
        .all()
    )
    return [_serialize_summary(setup) for setup in setups]


@router.get("/{symbol}")
def get_setup(symbol: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    setup = _get_setup_by_symbol(db, symbol)
    if setup is None:
        raise HTTPException(status_code=404, detail="Setup not found")
    return _serialize_setup(setup)


@router.delete("/{symbol}")
def delete_setup(symbol: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    setup = _get_setup_by_symbol(db, symbol)
    if setup is None:
        raise HTTPException(status_code=404, detail="Setup not found")
    db.delete(setup)
    db.commit()
    return {"deleted": True, "symbol": symbol}


@router.post("/scan")
async def scan_setup(request: ScanRequest) -> dict[str, Any]:
    if _scan_status.get("in_progress"):
        return {"status": "already_running"}

    estimated_count = _estimate_total_symbols(request)
    _scan_status["in_progress"] = True
    _scan_status["stage"] = "queued"
    _scan_status["total_symbols"] = estimated_count
    _scan_status["stage1_complete"] = 0
    _scan_status["stage2_complete"] = 0
    _scan_status["stage2_total"] = 0
    _scan_status["started_at"] = datetime.now(timezone.utc).isoformat()
    _scan_status["completed_at"] = None

    request_copy = ScanRequest(**request.model_dump())
    worker = threading.Thread(target=_run_scan_sync, args=(request_copy,), daemon=True)
    worker.start()

    return {
        "status": "scan_started",
        "total_symbols": estimated_count,
    }