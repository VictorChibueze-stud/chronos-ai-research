from __future__ import annotations

import json
import logging
from collections import Counter
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.adapters.binance_data import fetch_binance_ohlc_sync
from src.adapters.deriv_data import fetch_deriv_ohlc_sync
from src.adapters.yfinance_data import fetch_yfinance_ohlc_sync, is_yfinance_symbol
from src.core.filter_defaults import SCAN_AND_ANALYSIS_FILTER_DEFAULTS
from src.core.structural_walker import serialize_state_report, walk_structure
from src.core.features import compute_ema
from src.core.trend_id import compute_internal_structure, identify_trend
from src.api.universe_readiness import build_readiness_index, merge_readiness_fields
from src.db.models import (
    ActiveUniverseSymbol,
    MonitoredSetup,
    ScanSettings,
    ScanSettingsHistory,
    SignalHistory,
    UniverseBootstrapFailure,
    UniverseScore,
)
from src.scanner.global_structure import upsert_stored_walker_result
from src.services.structure_deepening import apply_tf_deepening_to_legs
from src.db.session import SessionLocal, get_db
from src.scanner.market_scanner import (
    DERIV_COMMODITY_SYMBOLS,
    DERIV_FOREX_SYMBOLS,
    DERIV_INDICES_SYMBOLS,
    fetch_top_symbols,
)
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

FILTER_CONFIG: dict[str, Any] = dict(SCAN_AND_ANALYSIS_FILTER_DEFAULTS)


def _yfinance_config_symbols() -> list[str]:
    raw = _SYMBOLS_DATA.get("yfinance") or []
    if isinstance(raw, dict):
        vals = [str(v).strip() for v in raw.values() if v is not None]
        return _normalize_symbol_list(vals)
    if not isinstance(raw, list):
        return []
    return _normalize_symbol_list([str(x) for x in raw])

MTF_LADDER: dict[str, list[str]] = {
    "1h": ["4h", "1d"],
    "4h": ["1d"],
    "15m": ["1h", "4h"],
    "5m": ["15m", "1h"],
}

BASE_FETCH_TIMEFRAME = "15m"
MAX_DERIV_WORKERS = 5
MAX_YFINANCE_WORKERS = 3

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
    "last_error": None,
}

_UNIVERSE_CACHE_TTL_SECONDS = 300
_universe_cache_lock = threading.Lock()
_universe_cache: dict[str, Any] = {
    "binance_symbols": set(),
    "updated_at": 0.0,
    "last_error": None,
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

ALLOWED_BROKERS = {"binance", "deriv", "yfinance"}
ALLOWED_DERIV_CATEGORIES = {"forex", "synthetic", "commodity", "indices", "crypto", "stocks", "etfs"}

MONITORED_CAPACITY = 50
CATEGORY_MIN_SLOT_KEYS = ("forex", "commodity", "indices", "synthetic", "crypto")
DEFAULT_CATEGORY_MIN_SLOTS: dict[str, int] = {
    "forex": 5,
    "commodity": 3,
    "indices": 3,
    "synthetic": 5,
    "crypto": 0,
}

DEFAULT_SCAN_SETTINGS: dict[str, Any] = {
    "binance_top_n": 350,
    "brokers": ["binance", "deriv", "yfinance"],
    "deriv_categories": ["forex", "synthetic", "commodity", "indices"],
    "include_symbols": [],
    "exclude_symbols": [],
    "score_weights": {
        "price_ratio_weight": 0.7,
        "bar_ratio_weight": 0.3,
    },
    "retracement_bonus": 10.0,
    "deriv_category_overrides": {},
    "enable_correlation_filter": False,
    "universe_scan_frequency": "daily",
    "active_refresh_hours": 4,
    "category_min_slots": dict(DEFAULT_CATEGORY_MIN_SLOTS),
}


class ScoreWeights(BaseModel):
    price_ratio_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    bar_ratio_weight: float = Field(default=0.3, ge=0.0, le=1.0)


class ScanSettingsPayload(BaseModel):
    binance_top_n: int = Field(default=350, ge=10, le=1000)
    brokers: list[str] = Field(default_factory=lambda: ["binance", "deriv", "yfinance"])
    deriv_categories: list[str] = Field(
        default_factory=lambda: ["forex", "synthetic", "commodity", "indices"]
    )
    include_symbols: list[str] = Field(default_factory=list)
    exclude_symbols: list[str] = Field(default_factory=list)
    score_weights: ScoreWeights = Field(default_factory=ScoreWeights)
    retracement_bonus: float = Field(default=10.0, ge=0.0, le=100.0)
    deriv_category_overrides: dict[str, str] = Field(default_factory=dict)
    enable_correlation_filter: bool = False
    universe_scan_frequency: str = Field(default="daily")
    active_refresh_hours: int = Field(default=4)


class ScanRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    timeframe: str = "1h"
    settings_override: ScanSettingsPayload | None = None


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


def _normalize_symbol_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        sym = str(raw or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def _normalize_scan_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = {**DEFAULT_SCAN_SETTINGS, **(raw or {})}

    try:
        top_n = int(data.get("binance_top_n", DEFAULT_SCAN_SETTINGS["binance_top_n"]))
    except (TypeError, ValueError):
        top_n = int(DEFAULT_SCAN_SETTINGS["binance_top_n"])
    data["binance_top_n"] = max(10, min(1000, top_n))

    brokers = [str(v).lower() for v in (data.get("brokers") or [])]
    brokers = [b for b in brokers if b in ALLOWED_BROKERS]
    data["brokers"] = brokers or list(DEFAULT_SCAN_SETTINGS["brokers"])

    deriv_categories = [str(v).lower() for v in (data.get("deriv_categories") or [])]
    deriv_categories = [c for c in deriv_categories if c in ALLOWED_DERIV_CATEGORIES]
    data["deriv_categories"] = deriv_categories or list(DEFAULT_SCAN_SETTINGS["deriv_categories"])

    data["include_symbols"] = _normalize_symbol_list(data.get("include_symbols"))
    data["exclude_symbols"] = _normalize_symbol_list(data.get("exclude_symbols"))

    sw = data.get("score_weights") or {}
    try:
        price_w = float(sw.get("price_ratio_weight", 0.7))
    except (TypeError, ValueError):
        price_w = 0.7
    try:
        bar_w = float(sw.get("bar_ratio_weight", 0.3))
    except (TypeError, ValueError):
        bar_w = 0.3
    total = price_w + bar_w
    if total <= 0:
        price_w, bar_w = 0.7, 0.3
        total = 1.0
    data["score_weights"] = {
        "price_ratio_weight": price_w / total,
        "bar_ratio_weight": bar_w / total,
    }

    try:
        bonus = float(data.get("retracement_bonus", DEFAULT_SCAN_SETTINGS["retracement_bonus"]))
    except (TypeError, ValueError):
        bonus = float(DEFAULT_SCAN_SETTINGS["retracement_bonus"])
    data["retracement_bonus"] = max(0.0, min(100.0, bonus))

    overrides: dict[str, str] = {}
    for k, v in (data.get("deriv_category_overrides") or {}).items():
        sym = str(k).strip().upper()
        cat = str(v).strip().lower()
        if sym and cat in ALLOWED_DERIV_CATEGORIES:
            overrides[sym] = cat
    data["deriv_category_overrides"] = overrides
    data["enable_correlation_filter"] = bool(
        data.get("enable_correlation_filter", DEFAULT_SCAN_SETTINGS["enable_correlation_filter"])
    )

    valid_universe_freqs = {"hourly", "daily", "weekly", "monthly"}
    freq = str(data.get("universe_scan_frequency", "daily")).lower()
    data["universe_scan_frequency"] = freq if freq in valid_universe_freqs else "daily"

    try:
        refresh_h = int(data.get("active_refresh_hours", 4))
    except (TypeError, ValueError):
        refresh_h = 4
    data["active_refresh_hours"] = refresh_h if refresh_h in {1, 2, 4, 8, 12, 24} else 4

    raw_mins = data.get("category_min_slots") or {}
    slot_out: dict[str, int] = {}
    for k in CATEGORY_MIN_SLOT_KEYS:
        try:
            v = int(raw_mins.get(k, DEFAULT_CATEGORY_MIN_SLOTS[k]))
        except (TypeError, ValueError):
            v = int(DEFAULT_CATEGORY_MIN_SLOTS[k])
        slot_out[k] = max(0, min(MONITORED_CAPACITY, v))
    sum_non_crypto = sum(slot_out[k] for k in CATEGORY_MIN_SLOT_KEYS if k != "crypto")
    if sum_non_crypto > MONITORED_CAPACITY:
        # Scale down non-crypto mins proportionally so the sum fits in capacity (crypto min stays as-is).
        logger.warning(
            "category_min_slots non-crypto sum %s > %s; scaling down proportionally",
            sum_non_crypto,
            MONITORED_CAPACITY,
        )
        scale = MONITORED_CAPACITY / float(sum_non_crypto)
        for k in CATEGORY_MIN_SLOT_KEYS:
            if k == "crypto":
                continue
            slot_out[k] = max(0, int(slot_out[k] * scale))
        while sum(slot_out[k] for k in CATEGORY_MIN_SLOT_KEYS if k != "crypto") > MONITORED_CAPACITY:
            reducible = [k for k in CATEGORY_MIN_SLOT_KEYS if k != "crypto" and slot_out[k] > 0]
            if not reducible:
                break
            drop_k = max(reducible, key=lambda x: slot_out[x])
            slot_out[drop_k] -= 1
    data["category_min_slots"] = slot_out

    return data


def _get_effective_scan_settings(db: Session) -> dict[str, Any]:
    row = db.query(ScanSettings).filter(ScanSettings.scope == "global").one_or_none()
    if row is None:
        normalized = _normalize_scan_settings(DEFAULT_SCAN_SETTINGS)
        now = datetime.now(timezone.utc)
        db.add(ScanSettings(scope="global", settings_json=normalized, updated_at=now))
        db.add(ScanSettingsHistory(scope="global", settings_json=normalized, created_at=now))
        db.commit()
        return normalized
    normalized = _normalize_scan_settings(row.settings_json if isinstance(row.settings_json, dict) else {})
    if normalized != row.settings_json:
        row.settings_json = normalized
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
    return normalized


def _save_scan_settings(db: Session, payload: ScanSettingsPayload) -> dict[str, Any]:
    normalized = _normalize_scan_settings(payload.model_dump())
    now = datetime.now(timezone.utc)
    row = db.query(ScanSettings).filter(ScanSettings.scope == "global").one_or_none()
    if row is None:
        row = ScanSettings(scope="global", settings_json=normalized, updated_at=now)
        db.add(row)
    else:
        row.settings_json = normalized
        row.updated_at = now
    db.add(ScanSettingsHistory(scope="global", settings_json=normalized, created_at=now))
    db.commit()
    return normalized


def _derive_deriv_category(
    symbol: str,
    market: str | None = None,
    submarket: str | None = None,
    overrides: dict[str, str] | None = None,
) -> str:
    sym = symbol.upper()
    # 3) manual override highest precedence
    override = (overrides or {}).get(sym)
    if override:
        return override

    if is_yfinance_symbol(sym):
        return "indices"

    # 1) API metadata when available
    market_l = str(market or "").lower()
    sub_l = str(submarket or "").lower()
    if market_l:
        if market_l == "forex":
            return "forex"
        if market_l in {"commodities", "commodity"}:
            return "commodity"
        if market_l in {"indices", "index", "synthetic_index"}:
            if "crash" in sub_l or "boom" in sub_l or "step" in sub_l or "random" in sub_l:
                return "synthetic"
            return "indices" if market_l == "indices" else "synthetic"
        if market_l == "cryptocurrency":
            return "crypto"
        if market_l == "stocks":
            return "stocks"
        if market_l == "etfs":
            return "etfs"

    # 2) regex/pattern fallback
    if sym in _COMMODITIES_SYMBOLS or sym.startswith("FRXX"):
        return "commodity"
    if sym in _INDICES_SYMBOLS:
        return "indices"
    if any(sym.startswith(prefix.upper()) for prefix in DERIV_SYNTHETIC_PREFIXES):
        return "synthetic"
    if sym.startswith("FRX") or (len(sym) == 6 and sym.isalpha()):
        return "forex"
    return "forex"


def _build_scan_symbol_universe(settings: dict[str, Any]) -> tuple[list[str], set[str] | None]:
    brokers = set(settings.get("brokers") or [])
    include_symbols = _normalize_symbol_list(settings.get("include_symbols"))
    exclude_symbols = set(_normalize_symbol_list(settings.get("exclude_symbols")))
    deriv_categories = set(settings.get("deriv_categories") or [])
    overrides = settings.get("deriv_category_overrides") or {}

    discovered: list[str] = []
    deriv_active_symbols: set[str] | None = None

    if "binance" in brokers:
        try:
            top_n = int(settings.get("binance_top_n", 350))
            discovered.extend(_normalize_symbol_list(fetch_top_symbols(n=top_n)))
        except Exception as e:  # noqa: BLE001
            logger.warning("Binance universe discovery failed: %s", e)

    if "deriv" in brokers:
        try:
            from src.adapters.deriv_data import get_active_deriv_symbols

            deriv_active_symbols = set(get_active_deriv_symbols())
            deriv_symbols = sorted(
                deriv_active_symbols
                | set(DERIV_FOREX_SYMBOLS)
                | set(DERIV_COMMODITY_SYMBOLS)
                | set(DERIV_INDICES_SYMBOLS)
            )
            for sym in deriv_symbols:
                cat = _derive_deriv_category(sym, overrides=overrides)
                if cat in deriv_categories:
                    discovered.append(sym)
        except Exception as e:  # noqa: BLE001
            logger.warning("Deriv universe discovery failed: %s", e)

    if "yfinance" in brokers:
        discovered.extend(_yfinance_config_symbols())

    # merge includes then apply excludes (exclude wins)
    discovered.extend(include_symbols)
    merged = _normalize_symbol_list(discovered)
    final_symbols = [s for s in merged if s not in exclude_symbols]
    return final_symbols, deriv_active_symbols


def _compute_hybrid_trend_score(result: dict[str, Any], settings: dict[str, Any]) -> tuple[float, dict[str, float]]:
    legs = [l for l in (result.get("legs") or []) if l.get("confirmed")]
    impulses = [l for l in legs if l.get("type") == "impulse"]
    retracements = [l for l in legs if l.get("type") == "retracement"]

    if len(legs) < 3:
        return 0.0, {
            "price_component": 0.0,
            "bar_component": 0.0,
            "retracement_bonus": 0.0,
            "price_ratio": 0.0,
            "bar_ratio": 0.0,
        }

    impulse_price = sum(
        abs(float(l.get("end_price", 0)) - float(l.get("start_price", 0)))
        for l in impulses
        if l.get("end_price") is not None and l.get("start_price") is not None
    )
    retr_price = sum(
        abs(float(l.get("end_price", 0)) - float(l.get("start_price", 0)))
        for l in retracements
        if l.get("end_price") is not None and l.get("start_price") is not None
    )
    price_ratio = impulse_price / max(retr_price, 1e-9)

    def _mean_velocity(leg_list):
        velocities = []
        for l in leg_list:
            sp = l.get("start_price")
            ep = l.get("end_price")
            si = l.get("start_index")
            ei = l.get("end_index")
            if None in (sp, ep, si, ei):
                continue
            bars = max(1, int(ei) - int(si))
            velocities.append(abs(float(ep) - float(sp)) / bars)
        return sum(velocities) / len(velocities) if velocities else 0.0

    impulse_velocity = _mean_velocity(impulses)
    retr_velocity = _mean_velocity(retracements)
    bar_ratio = impulse_velocity / max(retr_velocity, 1e-9)

    _LOG_DENOM = math.log2(11)
    price_component = min(100.0, max(0.0, (math.log2(price_ratio + 1) / _LOG_DENOM) * 100.0))
    bar_component = min(100.0, max(0.0, (math.log2(bar_ratio + 1) / _LOG_DENOM) * 100.0))

    weights = settings.get("score_weights") or {}
    price_w = float(weights.get("price_ratio_weight", 0.7))
    bar_w = float(weights.get("bar_ratio_weight", 0.3))

    base_score = (price_component * price_w) + (bar_component * bar_w)

    retracement_bonus = (
        float(settings.get("retracement_bonus", 15.0))
        if result.get("current_phase") == "retracement"
        else 0.0
    )

    total = min(100.0, max(0.0, base_score + retracement_bonus))

    return total, {
        "price_component": round(price_component, 2),
        "bar_component": round(bar_component, 2),
        "retracement_bonus": retracement_bonus,
        "price_ratio": round(price_ratio, 4),
        "bar_ratio": round(bar_ratio, 4),
    }


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
    score_components = state.get("score_components")
    score_components = state.get("score_components", {})

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
        "universe_rank": None,
        "timeframe": setup.htf_timeframe,
        "trend": global_trend,
        "current_phase": setup.current_phase or _infer_phase(state),
        "fsm_state": setup.status or "SCANNING",
        "ema_signal": setup.ema_signal or "WAITING",
        "trend_score": float(setup.trend_score or 0),
        "score_components": score_components if isinstance(score_components, dict) else None,
        "pullback_depth": pullback_depth,
        "total_mitigation_count": total_mitigation_count,
        "waiting_for": waiting_for,
        "active_choch_zone": active_choch_zone,
        "active_bos": active_bos,
        "active_zones": active_zones,
        "mtf_alignment": mtf_alignment,
        "structural_state": state,
        "structural_state_json": state,
        "score_components": score_components,
        "last_checked_at": setup.last_checked_at.isoformat() if setup.last_checked_at else None,
        "created_at": setup.created_at.isoformat() if setup.created_at else None,
    }


def _serialize_placeholder_setup(symbol: str, timeframe: str = "1h") -> dict[str, Any]:
    """Return a placeholder setup row for symbols without scan data."""
    inferred_category = _infer_category(symbol)
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "setup_id": None,
        "symbol": symbol,
        "broker": _derive_broker(symbol),
        "category": inferred_category,
        "timeframe": timeframe,
        "trend": "range",
        "current_phase": "range",
        "fsm_state": "UNSCANNED",
        "ema_signal": "WAITING",
        "trend_score": 0.0,
        "pullback_depth": 0,
        "total_mitigation_count": 0,
        "waiting_for": "Awaiting scan data",
        "active_choch_zone": None,
        "active_bos": None,
        "active_zones": [],
        "mtf_alignment": {},
        "structural_state": {},
        "structural_state_json": {},
        "score_components": {},
        "last_checked_at": now_iso,
        "created_at": None,
        "universe_rank": None,
    }


def _enrich_with_universe_scores(db: Session, rows: list[dict[str, Any]]) -> None:
    """Attach universe_rank and ranking timeframe_basis from universe_scores (batch)."""
    if not rows:
        return
    symbols_ordered: list[str] = []
    seen: set[str] = set()
    for row in rows:
        sym = str(row.get("symbol") or "").strip().upper()
        if sym and sym not in seen:
            seen.add(sym)
            symbols_ordered.append(sym)
    if not symbols_ordered:
        return
    score_by_symbol: dict[str, UniverseScore] = {}
    chunk = 500
    for i in range(0, len(symbols_ordered), chunk):
        part = symbols_ordered[i : i + chunk]
        for us in db.query(UniverseScore).filter(UniverseScore.symbol.in_(part)).all():
            score_by_symbol[str(us.symbol).upper()] = us
    for row in rows:
        sym = str(row.get("symbol") or "").strip().upper()
        us = score_by_symbol.get(sym)
        if us is None:
            row.setdefault("universe_rank", None)
            continue
        row["universe_rank"] = us.universe_rank
        row["timeframe_basis"] = us.timeframe_basis


def _infer_category(symbol: str) -> str:
    """Infer asset category from symbol name."""
    symbol_upper = symbol.upper()
    if symbol_upper.endswith("USDT") or symbol_upper.endswith("BTC"):
        return "crypto"
    return _derive_deriv_category(symbol_upper, overrides={**(DEFAULT_SCAN_SETTINGS.get("deriv_category_overrides") or {})})


def _monitored_setup_category(symbol: str, settings: dict[str, Any]) -> str:
    """Lowercase category for eviction minimums; uses scan-settings overrides."""
    sym = symbol.upper()
    if sym.endswith("USDT") or sym.endswith("BTC"):
        return "crypto"
    return str(
        _derive_deriv_category(sym, overrides=settings.get("deriv_category_overrides") or {})
    ).lower()


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
    cat = _derive_deriv_category(normalized)
    if cat == "commodity":
        return "COMMODITIES"
    if cat == "indices":
        return "INDICES"
    if cat == "synthetic":
        return "SYNTHETIC"
    if cat == "crypto":
        return "CRYPTO"
    if cat == "stocks":
        return "STOCKS"
    if cat == "etfs":
        return "ETFS"
    return "FOREX"


def _derive_broker(symbol: str) -> str:
    normalized = symbol.upper()
    if normalized.endswith("USDT") or normalized.endswith("BTC"):
        return "binance"
    if is_yfinance_symbol(normalized):
        return "yfinance"
    return "deriv"


def refresh_universe_cache() -> None:
    """Refresh Binance top-symbol universe cache in-process."""
    started = time.time()
    try:
        db = SessionLocal()
        try:
            settings = _get_effective_scan_settings(db)
            top_n = int(settings.get("binance_top_n", 350))
        finally:
            db.close()
        symbols = {str(sym).upper() for sym in fetch_top_symbols(n=top_n)}
    except Exception as exc:  # noqa: BLE001
        with _universe_cache_lock:
            _universe_cache["last_error"] = str(exc)
        logger.warning("Universe cache refresh failed: %s", exc)
        return

    with _universe_cache_lock:
        _universe_cache["binance_symbols"] = symbols
        _universe_cache["updated_at"] = started
        _universe_cache["last_error"] = None
    logger.info("Universe cache refreshed: %d Binance symbols", len(symbols))


def get_universe_binance_symbols() -> set[str]:
    """Return cached Binance universe and trigger async refresh when stale."""
    should_refresh = False
    with _universe_cache_lock:
        symbols = set(_universe_cache["binance_symbols"])
        updated_at = float(_universe_cache["updated_at"] or 0.0)

    if not symbols:
        refresh_universe_cache()
        with _universe_cache_lock:
            return set(_universe_cache["binance_symbols"])

    if (time.time() - updated_at) >= _UNIVERSE_CACHE_TTL_SECONDS:
        should_refresh = True

    if should_refresh:
        threading.Thread(target=refresh_universe_cache, daemon=True).start()

    return symbols


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


def _write_stage1_result(
    symbol: str,
    data: dict[str, Any],
    timeframe: str,
    db: Session,
    *,
    evict: bool = True,
) -> None:
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
    if evict:
        _evict_to_capacity(db, capacity=MONITORED_CAPACITY)


def _record_bootstrap_failure(db: Session, symbol: str, message: str) -> None:
    norm = symbol.strip().upper()
    now = datetime.now(timezone.utc)
    msg = (message or "")[:2000]
    existing = (
        db.query(UniverseBootstrapFailure)
        .filter(UniverseBootstrapFailure.symbol == norm)
        .one_or_none()
    )
    if existing is not None:
        existing.failed_at = now
        existing.error_message = msg
    else:
        db.add(
            UniverseBootstrapFailure(symbol=norm, failed_at=now, error_message=msg)
        )
    db.commit()


def _clear_bootstrap_failure(db: Session, symbol: str) -> None:
    norm = symbol.strip().upper()
    row = (
        db.query(UniverseBootstrapFailure)
        .filter(UniverseBootstrapFailure.symbol == norm)
        .one_or_none()
    )
    if row is not None:
        db.delete(row)
        db.commit()


def _stage1_binance_single(
    symbol: str,
    request_timeframe: str,
    base_start_time: datetime,
) -> dict[str, Any] | None:
    """Fetch + identify_trend for one Binance symbol (same logic as batch stage 1)."""
    try:
        base_candles = fetch_binance_ohlc_sync(
            symbol,
            BASE_FETCH_TIMEFRAME,
            start_time=base_start_time,
        )
        if not base_candles:
            return None

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

        requested_minutes = RESAMPLE_MINUTES.get(request_timeframe)
        if requested_minutes is None:
            primary_candles = fetch_binance_ohlc_sync(
                symbol,
                request_timeframe,
                start_time=base_start_time,
            )
        elif request_timeframe == BASE_FETCH_TIMEFRAME:
            primary_candles = base_candles
        else:
            primary_candles = _resample_candles(base_candles, requested_minutes)

        if len(primary_candles) < 50:
            try:
                primary_candles = fetch_binance_ohlc_sync(
                    symbol,
                    request_timeframe,
                    start_time=base_start_time,
                )
            except Exception:
                pass

        if not primary_candles:
            return None

        result = identify_trend(primary_candles, **FILTER_CONFIG)
        compute_internal_structure(primary_candles, result["legs"], **FILTER_CONFIG)
        return {
            "candles": primary_candles,
            "result": result,
            "mtf_alignment": mtf_alignment,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("Binance stage1 single failed for %s: %s", symbol, e)
        return None


def _bootstrap_stage1_symbol(
    db: Session,
    symbol: str,
    timeframe: str = "1h",
) -> MonitoredSetup | None:
    """On-demand stage 1: persist MonitoredSetup or record failure. Does not evict other rows."""
    normalized = symbol.strip().upper()
    base_tf_config = _TF_WINDOWS.get("timeframes", {}).get(BASE_FETCH_TIMEFRAME, {})
    base_lookback_days: float = base_tf_config.get("lookback_days", 7.5)
    base_start_time = datetime.now(timezone.utc) - timedelta(days=base_lookback_days)

    is_binance = normalized.endswith("USDT") or normalized.endswith("BTC")
    data: dict[str, Any] | None = None
    if is_binance:
        data = _stage1_binance_single(normalized, timeframe, base_start_time)
    elif is_yfinance_symbol(normalized):
        _, data = _process_yfinance_symbol(
            normalized,
            timeframe,
            FILTER_CONFIG,
            base_start_time,
        )
    else:
        deriv_active: set[str] | None = None
        try:
            from src.adapters.deriv_data import get_active_deriv_symbols

            deriv_active = set(get_active_deriv_symbols())
        except Exception:
            deriv_active = None
        _, data = _process_deriv_symbol(
            normalized,
            timeframe,
            FILTER_CONFIG,
            base_start_time,
            deriv_active,
        )

    if not data:
        _record_bootstrap_failure(db, normalized, "No candles or stage-1 failed")
        return None

    try:
        _write_stage1_result(normalized, data, timeframe, db, evict=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bootstrap write failed for %s: %s", normalized, exc)
        _record_bootstrap_failure(db, normalized, str(exc))
        return None

    _clear_bootstrap_failure(db, normalized)
    return _get_setup_by_symbol(db, normalized)


def _record_signal_history(
    db: Session,
    symbol: str,
    timeframe: str,
    signal: str,
    trend_direction: str | None,
    trend_score: float | None,
) -> None:
    if signal not in {"LONG", "SHORT"}:
        return
    latest = (
        db.query(SignalHistory)
        .filter(
            SignalHistory.symbol == symbol,
            SignalHistory.timeframe == timeframe,
        )
        .order_by(SignalHistory.emitted_at.desc(), SignalHistory.id.desc())
        .first()
    )
    if latest is not None and latest.signal == signal:
        return
    db.add(
        SignalHistory(
            symbol=symbol,
            timeframe=timeframe,
            signal=signal,
            trend_direction=trend_direction,
            trend_score=trend_score,
            emitted_at=datetime.now(timezone.utc),
        )
    )
    db.commit()


def _process_deriv_symbol(
    symbol: str,
    timeframe: str,
    filter_config: dict[str, Any],
    base_start_time: datetime,
    active_symbols: set[str] | None,
) -> tuple[str, dict[str, Any] | None]:
    """Process one Deriv symbol for Stage 1.

    Mirrors Binance: fetch 15m base, resample to 30m/1h/4h, build mtf_alignment
    from identify_trend on each (only ``up`` / ``down`` keys kept).
    """
    try:
        base_candles = fetch_deriv_ohlc_sync(
            symbol,
            BASE_FETCH_TIMEFRAME,
            start_time=base_start_time,
            active_symbols=active_symbols,
        )
        if not base_candles:
            return symbol, None

        base_result = identify_trend(base_candles, **filter_config)

        mtf_alignment: dict[str, str] = {}
        if base_result.get("trend") in ("up", "down"):
            mtf_alignment[BASE_FETCH_TIMEFRAME] = base_result.get("trend", "unknown")
        for tf in ["30m", "1h", "4h"]:
            target_minutes = RESAMPLE_MINUTES[tf]
            try:
                tf_candles = _resample_candles(base_candles, target_minutes)
                if not tf_candles:
                    continue
                tf_result = identify_trend(tf_candles, **filter_config)
                tf_trend = tf_result.get("trend", "unknown")
                if tf_trend in ("up", "down"):
                    mtf_alignment[tf] = tf_trend
            except Exception:
                continue

        requested_minutes = RESAMPLE_MINUTES.get(timeframe)
        if requested_minutes is None:
            primary_candles = fetch_deriv_ohlc_sync(
                symbol,
                timeframe,
                start_time=base_start_time,
                active_symbols=active_symbols,
            )
        elif timeframe == BASE_FETCH_TIMEFRAME:
            primary_candles = base_candles
        else:
            primary_candles = _resample_candles(base_candles, requested_minutes)

        if len(primary_candles) < 50:
            try:
                tf_cfg = _TF_WINDOWS.get("timeframes", {}).get(timeframe, {})
                lb = float(tf_cfg.get("lookback_days", 100.0))
                fb_start = datetime.now(timezone.utc) - timedelta(days=lb)
                primary_candles = fetch_deriv_ohlc_sync(
                    symbol,
                    timeframe,
                    start_time=fb_start,
                    active_symbols=active_symbols,
                )
            except Exception:
                pass

        if not primary_candles:
            return symbol, None

        result = identify_trend(primary_candles, **filter_config)
        compute_internal_structure(primary_candles, result["legs"], **filter_config)
        return symbol, {
            "candles": primary_candles,
            "result": result,
            "mtf_alignment": mtf_alignment,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("Deriv Stage 1 failed for %s: %s", symbol, e)
        return symbol, None


def _process_yfinance_symbol(
    symbol: str,
    timeframe: str,
    filter_config: dict[str, Any],
    base_start_time: datetime,
) -> tuple[str, dict[str, Any] | None]:
    """Stage 1 for Yahoo Finance symbols: 15m base, resample MTF like Deriv path."""
    try:
        base_candles = fetch_yfinance_ohlc_sync(
            symbol,
            BASE_FETCH_TIMEFRAME,
            start_time=base_start_time,
        )
        if not base_candles:
            return symbol, None

        base_result = identify_trend(base_candles, **filter_config)

        mtf_alignment: dict[str, str] = {}
        if base_result.get("trend") in ("up", "down"):
            mtf_alignment[BASE_FETCH_TIMEFRAME] = base_result.get("trend", "unknown")
        for tf in ["30m", "1h", "4h"]:
            target_minutes = RESAMPLE_MINUTES[tf]
            try:
                tf_candles = _resample_candles(base_candles, target_minutes)
                if not tf_candles:
                    continue
                tf_result = identify_trend(tf_candles, **filter_config)
                tf_trend = tf_result.get("trend", "unknown")
                if tf_trend in ("up", "down"):
                    mtf_alignment[tf] = tf_trend
            except Exception:
                continue

        requested_minutes = RESAMPLE_MINUTES.get(timeframe)
        if requested_minutes is None:
            primary_candles = fetch_yfinance_ohlc_sync(
                symbol,
                timeframe,
                start_time=base_start_time,
            )
        elif timeframe == BASE_FETCH_TIMEFRAME:
            primary_candles = base_candles
        else:
            primary_candles = _resample_candles(base_candles, requested_minutes)

        if len(primary_candles) < 50:
            try:
                tf_cfg = _TF_WINDOWS.get("timeframes", {}).get(timeframe, {})
                lb = float(tf_cfg.get("lookback_days", 100.0))
                fb_start = datetime.now(timezone.utc) - timedelta(days=lb)
                primary_candles = fetch_yfinance_ohlc_sync(
                    symbol,
                    timeframe,
                    start_time=fb_start,
                )
            except Exception:
                pass

        if not primary_candles:
            return symbol, None

        result = identify_trend(primary_candles, **filter_config)
        compute_internal_structure(primary_candles, result["legs"], **filter_config)
        return symbol, {
            "candles": primary_candles,
            "result": result,
            "mtf_alignment": mtf_alignment,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("Yahoo Finance Stage 1 failed for %s: %s", symbol, e)
        return symbol, None


def _estimate_total_symbols(request: ScanRequest, settings: dict[str, Any]) -> int:
    if request.symbols:
        return len(_normalize_symbol_list(request.symbols))
    include_symbols = _normalize_symbol_list(settings.get("include_symbols"))
    exclude_symbols = set(_normalize_symbol_list(settings.get("exclude_symbols")))
    base_estimate = 0
    brokers = set(settings.get("brokers") or [])
    if "binance" in brokers:
        base_estimate += int(settings.get("binance_top_n", 350))
    if "deriv" in brokers:
        deriv_symbols = {
            str(code).upper()
            for code in (_SYMBOLS_DATA.get("deriv") or {}).values()
        }
        base_estimate += len(deriv_symbols | _COMMODITIES_SYMBOLS | _INDICES_SYMBOLS)
    if "yfinance" in brokers:
        base_estimate += len(_yfinance_config_symbols())
    included_count = len(include_symbols)
    return max(0, base_estimate + included_count - len(exclude_symbols))


def _evict_to_capacity(
    db: Session,
    capacity: int = MONITORED_CAPACITY,
    settings: dict[str, Any] | None = None,
) -> None:
    if settings is None:
        settings = _get_effective_scan_settings(db)
    else:
        settings = _normalize_scan_settings(settings)
    mins: dict[str, int] = settings.get("category_min_slots") or dict(DEFAULT_CATEGORY_MIN_SLOTS)

    rows = list(
        db.execute(
            text(
                """
                SELECT ms.id, ms.symbol, ms.trend_score,
                       CASE
                           WHEN EXISTS (
                               SELECT 1
                               FROM alert_zones az
                               WHERE az.setup_id = ms.id
                                 AND az.is_manual_override IS TRUE
                                 AND az.is_active IS TRUE
                           )
                           THEN 1
                           ELSE 0
                       END AS is_protected
                FROM monitored_setups ms
                ORDER BY ms.trend_score DESC, ms.id ASC
                """
            )
        ).mappings().all()
    )
    if len(rows) <= capacity:
        return

    row_by_id: dict[int, dict[str, Any]] = {}
    for r in rows:
        rid = int(r["id"])
        row_by_id[rid] = {
            "id": rid,
            "symbol": str(r["symbol"]),
            "trend_score": float(r["trend_score"] or 0.0),
            "is_protected": bool(r["is_protected"]),
        }

    retain: set[int] = {int(rows[i]["id"]) for i in range(capacity)}

    def category_counts(retain_ids: set[int]) -> dict[str, int]:
        c: Counter[str] = Counter()
        for rid in retain_ids:
            cat = _monitored_setup_category(row_by_id[rid]["symbol"], settings)
            c[cat] += 1
        return dict(c)

    max_swaps = max(capacity * 10, 100)
    for _ in range(max_swaps):
        counts = category_counts(retain)
        deficit: str | None = None
        for ckey in CATEGORY_MIN_SLOT_KEYS:
            need = int(mins.get(ckey, 0))
            if need > 0 and counts.get(ckey, 0) < need:
                deficit = ckey
                break
        if deficit is None:
            break

        outsider_candidates = [
            int(r["id"])
            for r in rows
            if int(r["id"]) not in retain
            and not bool(r["is_protected"])
            and _monitored_setup_category(str(r["symbol"]), settings) == deficit
        ]
        outsider_candidates.sort(
            key=lambda rid: (-row_by_id[rid]["trend_score"], row_by_id[rid]["id"])
        )
        if not outsider_candidates:
            logger.warning(
                "Eviction: cannot satisfy category_min_slots for %r — no unprotected outsiders",
                deficit,
            )
            break
        out_id = outsider_candidates[0]

        insider_candidates: list[int] = []
        for rid in retain:
            if row_by_id[rid]["is_protected"]:
                continue
            d = _monitored_setup_category(row_by_id[rid]["symbol"], settings)
            if counts.get(d, 0) > int(mins.get(d, 0)):
                insider_candidates.append(rid)
        insider_candidates.sort(
            key=lambda rid: (row_by_id[rid]["trend_score"], row_by_id[rid]["id"])
        )
        if not insider_candidates:
            logger.warning(
                "Eviction: cannot satisfy category_min_slots for %r — no swappable insiders",
                deficit,
            )
            break
        in_id = insider_candidates[0]
        retain.remove(in_id)
        retain.add(out_id)
        logger.info(
            "Eviction swap: pull in %s (score=%.1f) for mins, drop %s (score=%.1f)",
            row_by_id[out_id]["symbol"],
            row_by_id[out_id]["trend_score"],
            row_by_id[in_id]["symbol"],
            row_by_id[in_id]["trend_score"],
        )

    to_evict_ids = [
        int(r["id"])
        for r in rows
        if not bool(r["is_protected"]) and int(r["id"]) not in retain
    ]
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


def _run_scan_sync(request: ScanRequest, settings: dict[str, Any] | None = None) -> None:
    db = SessionLocal()
    try:
        effective_settings = _normalize_scan_settings(settings or DEFAULT_SCAN_SETTINGS)
        _evict_to_capacity(db, capacity=MONITORED_CAPACITY, settings=effective_settings)
        symbols = _normalize_symbol_list(request.symbols)
        deriv_active_symbols: set[str] | None = None

        # Auto-discover universe if no symbols provided
        if not symbols:
            symbols, deriv_active_symbols = _build_scan_symbol_universe(effective_settings)

            if not symbols:
                raise RuntimeError(
                    "Universe discovery failed — no symbols found from Binance, Deriv, or Yahoo Finance"
                )

            logger.info("Full universe: %d symbols to scan", len(symbols))

        _scan_status["in_progress"] = True
        _scan_status["stage"] = "stage1"
        _scan_status["total_symbols"] = len(symbols)
        _scan_status["stage1_complete"] = 0
        _scan_status["stage2_complete"] = 0
        _scan_status["stage2_total"] = 0
        _scan_status["started_at"] = datetime.now(timezone.utc).isoformat()
        _scan_status["completed_at"] = None
        _scan_status["last_error"] = None

        stage1_results: dict[str, dict[str, Any]] = {}
        base_tf_config = _TF_WINDOWS.get("timeframes", {}).get(BASE_FETCH_TIMEFRAME, {})
        base_lookback_days: float = base_tf_config.get("lookback_days", 7.5)
        base_start_time = datetime.now(timezone.utc) - timedelta(days=base_lookback_days)

        binance_symbols = [
            s for s in symbols if s.upper().endswith("USDT") or s.upper().endswith("BTC")
        ]
        yfinance_symbols = [s for s in symbols if is_yfinance_symbol(s)]
        deriv_symbols = [
            s
            for s in symbols
            if not (s.upper().endswith("USDT") or s.upper().endswith("BTC"))
            and not is_yfinance_symbol(s)
        ]

        for symbol in binance_symbols:
            try:
                data = _stage1_binance_single(symbol, request.timeframe, base_start_time)
                if not data:
                    continue
                stage1_results[symbol] = data
                _write_stage1_result(symbol, data, request.timeframe, db, evict=False)
                _scan_status["stage1_complete"] += 1
                res = data["result"]
                logger.info(
                    "Stage 1 complete: %s trend=%s phase=%s",
                    symbol,
                    res.get("trend"),
                    res.get("current_phase"),
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("Stage 1 failed for %s: %s", symbol, e)
                continue

        if yfinance_symbols:
            n_workers = min(MAX_YFINANCE_WORKERS, len(yfinance_symbols))
            logger.warning(
                "Stage 1 Yahoo Finance concurrent start: symbols=%d max_workers=%d",
                len(yfinance_symbols),
                n_workers,
            )
            with ThreadPoolExecutor(max_workers=n_workers) as executor:
                futures = {
                    executor.submit(
                        _process_yfinance_symbol,
                        sym,
                        request.timeframe,
                        FILTER_CONFIG,
                        base_start_time,
                    ): sym
                    for sym in yfinance_symbols
                }
                for future in as_completed(futures):
                    symbol = futures[future]
                    try:
                        resolved_symbol, data = future.result()
                    except Exception as e:  # noqa: BLE001
                        logger.warning("Yahoo Finance Stage 1 future failed for %s: %s", symbol, e)
                        continue
                    if data is None:
                        continue
                    stage1_results[resolved_symbol] = data
                    _write_stage1_result(resolved_symbol, data, request.timeframe, db, evict=False)
                    _scan_status["stage1_complete"] += 1

        if deriv_symbols:
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
                        base_start_time,
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
                    _write_stage1_result(resolved_symbol, data, request.timeframe, db, evict=False)
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

                apply_tf_deepening_to_legs(
                    candles, result["legs"], FILTER_CONFIG, symbol
                )
                state_report = walk_structure(
                    candles,
                    result,
                    FILTER_CONFIG,
                    max_depth=3,
                    symbol=symbol,
                    deepening_timeframes=["4h", "1h", "30m"],
                )
                serialized = serialize_state_report(state_report)
                upsert_stored_walker_result(
                    db, symbol, request.timeframe, serialized
                )
                depth = serialized.get("max_depth_reached", 0)
                mitigations = serialized.get("total_mitigation_count", 0)
                trend_score, score_components = _compute_hybrid_trend_score(result, effective_settings)
                serialized["score_components"] = score_components

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
                    existing.current_phase = result.get("current_phase")
                    existing.htf_trend_direction = result.get("trend")
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
                _evict_to_capacity(db, capacity=MONITORED_CAPACITY, settings=effective_settings)
                _record_signal_history(
                    db=db,
                    symbol=symbol,
                    timeframe=request.timeframe,
                    signal=ema_signal,
                    trend_direction=result.get("trend"),
                    trend_score=trend_score,
                )

                _scan_status["stage2_complete"] += 1
                logger.info(
                    "Stage 2 complete: %s depth=%s mitigations=%s score=%s components=%s",
                    symbol,
                    depth,
                    mitigations,
                    trend_score,
                    score_components,
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
                    apply_tf_deepening_to_legs(
                        cu_candles, cu_result["legs"], FILTER_CONFIG, setup.symbol
                    )

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
                        symbol=setup.symbol,
                        deepening_timeframes=["4h", "1h", "30m"],
                    )
                    cu_serialized = serialize_state_report(cu_state_report)
                    upsert_stored_walker_result(
                        db,
                        setup.symbol,
                        (setup.htf_timeframe or "1h").strip().lower(),
                        cu_serialized,
                    )
                    cu_depth = cu_serialized.get("max_depth_reached", 0)
                    cu_mitigations = cu_serialized.get("total_mitigation_count", 0)
                    cu_score, _cu_components = _compute_hybrid_trend_score(cu_result, effective_settings)
                    cu_serialized["score_components"] = _cu_components

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
                    _record_signal_history(
                        db=db,
                        symbol=setup.symbol,
                        timeframe=setup.htf_timeframe,
                        signal=cu_ema_signal,
                        trend_direction=cu_result.get("trend"),
                        trend_score=cu_score,
                    )
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

            correlation_enabled = bool(effective_settings.get("enable_correlation_filter", False))
            if all_setups and stage1_results and correlation_enabled:
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
            elif all_setups and stage1_results and not correlation_enabled:
                logger.info("Stage 3 correlation filter skipped: disabled by scan settings")
            else:
                logger.info(
                    "Stage 3 correlation filter skipped: no Stage 1 candle set available for this scan"
                )

            _scan_status["stage"] = "stage3_eviction"
            _evict_to_capacity(db, capacity=MONITORED_CAPACITY, settings=effective_settings)
            _scan_status["stage"] = "complete"
        except Exception as e:  # noqa: BLE001
            logger.warning("Stage 3 correlation/eviction failed: %s", e)
            _scan_status["stage"] = "failed"
            _scan_status["last_error"] = str(e)
    except Exception as e:  # noqa: BLE001
        logger.exception("Background scan failed: %s", e)
        _scan_status["stage"] = "failed"
        _scan_status["last_error"] = str(e)
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
    out = [_serialize_setup(setup) for setup in setups]
    _enrich_with_universe_scores(db, out)
    return out


@router.get("/universe")
def list_setups_universe(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """
    Return full universe rows:
    - all Deriv symbols from config/symbols.yaml
    - top 350 Binance symbols by volume
    Includes placeholders when no monitored setup exists yet.
    Each row includes readiness_state (FULL / PARTIAL / ERROR / UNSCANNED).
    """
    setup_rows = (
        db.query(MonitoredSetup)
        .order_by(MonitoredSetup.symbol.asc(), MonitoredSetup.trend_score.desc(), MonitoredSetup.id.asc())
        .all()
    )

    best_setup_by_symbol: dict[str, MonitoredSetup] = {}
    for row in setup_rows:
        key = row.symbol.upper()
        if key not in best_setup_by_symbol:
            best_setup_by_symbol[key] = row

    settings = _get_effective_scan_settings(db)
    brokers = set(settings.get("brokers") or [])
    deriv_categories = set(settings.get("deriv_categories") or [])
    overrides = settings.get("deriv_category_overrides") or {}

    deriv_symbols: set[str] = set()
    if "deriv" in brokers:
        candidate_deriv = (
            {str(code).upper() for code in (_SYMBOLS_DATA.get("deriv") or {}).values()}
            | set(DERIV_FOREX_SYMBOLS)
            | set(DERIV_COMMODITY_SYMBOLS)
            | set(DERIV_INDICES_SYMBOLS)
        )
        deriv_symbols = {
            sym for sym in candidate_deriv
            if _derive_deriv_category(sym, overrides=overrides) in deriv_categories
        }

    binance_symbols: set[str] = set()
    if "binance" in brokers:
        try:
            top_n = int(settings.get("binance_top_n", 350))
            binance_symbols = set(_normalize_symbol_list(fetch_top_symbols(n=top_n)))
        except Exception:
            binance_symbols = get_universe_binance_symbols()

    yfinance_symbols_set: set[str] = set()
    if "yfinance" in brokers:
        yfinance_symbols_set = set(_yfinance_config_symbols())

    include_symbols = set(_normalize_symbol_list(settings.get("include_symbols")))
    exclude_symbols = set(_normalize_symbol_list(settings.get("exclude_symbols")))
    universe_symbols = sorted(
        (deriv_symbols | binance_symbols | yfinance_symbols_set | include_symbols) - exclude_symbols
    )
    readiness_index = build_readiness_index(db, universe_symbols)

    payload: list[dict[str, Any]] = []
    for symbol in universe_symbols:
        existing = best_setup_by_symbol.get(symbol)
        if existing is not None:
            row = _serialize_setup(existing)
        else:
            row = _serialize_placeholder_setup(symbol)
        merge_readiness_fields(row, readiness_index.get(symbol, {}))
        payload.append(row)

    payload.sort(
        key=lambda row: (
            str(row.get("category") or ""),
            str(row.get("symbol") or ""),
        )
    )
    _enrich_with_universe_scores(db, payload)
    return payload


@router.get("/summary")
def list_setups_summary(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    setups = (
        db.query(MonitoredSetup)
        .order_by(MonitoredSetup.trend_score.desc(), MonitoredSetup.id.asc())
        .all()
    )
    return [_serialize_summary(setup) for setup in setups]


@router.get("/active-list")
def get_active_list(db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = (
        db.query(ActiveUniverseSymbol)
        .order_by(ActiveUniverseSymbol.symbol.asc())
        .all()
    )
    return {"symbols": [row.symbol for row in rows]}


@router.post("/active-list/{symbol}")
def add_active_symbol(symbol: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    normalized = symbol.strip().upper()
    if not normalized:
        raise HTTPException(status_code=400, detail="Symbol is required")
    existing = (
        db.query(ActiveUniverseSymbol)
        .filter(ActiveUniverseSymbol.symbol == normalized)
        .one_or_none()
    )
    if existing is None:
        db.add(ActiveUniverseSymbol(symbol=normalized))
        db.commit()
    return {"ok": True, "symbol": normalized}


@router.delete("/active-list/{symbol}")
def remove_active_symbol(symbol: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    normalized = symbol.strip().upper()
    row = (
        db.query(ActiveUniverseSymbol)
        .filter(ActiveUniverseSymbol.symbol == normalized)
        .one_or_none()
    )
    if row is not None:
        db.delete(row)
        db.commit()
    return {"ok": True, "symbol": normalized}


@router.get("/scan-settings")
def get_scan_settings(db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = _get_effective_scan_settings(db)
    return settings


@router.post("/scan-settings")
def save_scan_settings(payload: ScanSettingsPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    result = _save_scan_settings(db, payload)
    try:
        from src.api.main import apply_scan_schedule_from_db

        apply_scan_schedule_from_db(db)
    except Exception:
        logger.exception("Failed to apply scan schedule after save")
    return result


@router.get("/scan-settings/history")
def get_scan_settings_history(limit: int = 20, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = (
        db.query(ScanSettingsHistory)
        .filter(ScanSettingsHistory.scope == "global")
        .order_by(ScanSettingsHistory.created_at.desc(), ScanSettingsHistory.id.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    return [
        {
            "id": row.id,
            "scope": row.scope,
            "settings": _normalize_scan_settings(row.settings_json if isinstance(row.settings_json, dict) else {}),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@router.get("/{symbol}")
def get_setup(symbol: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    normalized = symbol.strip().upper()
    setup = _get_setup_by_symbol(db, normalized)
    if setup is None:
        setup = _bootstrap_stage1_symbol(db, normalized, "1h")
    if setup is None:
        placeholder = _serialize_placeholder_setup(normalized)
        idx = build_readiness_index(db, [normalized]).get(normalized, {})
        merge_readiness_fields(placeholder, idx)
        fail = (
            db.query(UniverseBootstrapFailure)
            .filter(UniverseBootstrapFailure.symbol == normalized)
            .one_or_none()
        )
        placeholder["readiness_error"] = (
            (fail.error_message or "Bootstrap failed") if fail else "Bootstrap failed"
        )
        placeholder["readiness_state"] = "ERROR"
        _enrich_with_universe_scores(db, [placeholder])
        return placeholder
    row = _serialize_setup(setup)
    merge_readiness_fields(row, build_readiness_index(db, [normalized]).get(normalized, {}))
    _enrich_with_universe_scores(db, [row])
    return row


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

    db = SessionLocal()
    try:
        base_settings = _get_effective_scan_settings(db)
    finally:
        db.close()
    effective_settings = (
        _normalize_scan_settings(request.settings_override.model_dump())
        if request.settings_override is not None
        else base_settings
    )
    estimated_count = _estimate_total_symbols(request, effective_settings)
    _scan_status["in_progress"] = True
    _scan_status["stage"] = "queued"
    _scan_status["total_symbols"] = estimated_count
    _scan_status["stage1_complete"] = 0
    _scan_status["stage2_complete"] = 0
    _scan_status["stage2_total"] = 0
    _scan_status["started_at"] = datetime.now(timezone.utc).isoformat()
    _scan_status["completed_at"] = None
    _scan_status["last_error"] = None

    request_copy = ScanRequest(**request.model_dump())
    worker = threading.Thread(target=_run_scan_sync, args=(request_copy, effective_settings), daemon=True)
    worker.start()

    return {
        "status": "scan_started",
        "total_symbols": estimated_count,
    }