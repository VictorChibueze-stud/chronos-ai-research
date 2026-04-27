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
from src.adapters.yfinance_data import (
    fetch_yfinance_ohlc_sync,
    get_display_name,
    get_sector,
    is_yfinance_symbol,
)
from src.core.filter_defaults import SCAN_AND_ANALYSIS_FILTER_DEFAULTS
from src.core.structural_walker import serialize_state_report, walk_structure
from src.core.features import compute_ema
from src.core.trend_id import compute_internal_structure, identify_trend
from src.api.universe_readiness import build_readiness_index, merge_readiness_fields
from src.analysis.recompute_orchestrator import recompute_full_chain_for_symbol
from src.db.models import (
    ActiveUniverseSymbol,
    CandidateImpulseCache,
    GlobalStructureCache,
    MonitoredSetup,
    ScanSettings,
    ScanSettingsHistory,
    SignalHistory,
    UniverseBootstrapFailure,
    UniverseScore,
    UniverseSettings,
)
from src.cache.candle_store import refresh_candles
from src.scanner.global_structure import (
    compute_and_write_market_state,
    get_stored_candidate_impulse,
    get_stored_global_structure,
    upsert_stored_walker_result,
)
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
_STAGE2_MAX_CONCURRENT = 5
_stage2_semaphore = threading.Semaphore(_STAGE2_MAX_CONCURRENT)

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
    "paper_engine": None,
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
YFINANCE_CATEGORY_MAP: dict[str, str] = {
    # Stock indices
    "SPX500": "indices",
    "NAS100": "indices",
    "DAX40": "indices",
    "FTSE100": "indices",
    "NKY225": "indices",
    "HSI": "indices",
    "CAC40": "indices",
    "ASX200": "indices",
    # Forex — all FRX prefix symbols
    "FRXEURUSD": "forex",
    "FRXGBPUSD": "forex",
    "FRXUSDJPY": "forex",
    "FRXUSDCHF": "forex",
    "FRXAUDUSD": "forex",
    "FRXUSDCAD": "forex",
    "FRXNZDUSD": "forex",
    "FRXEURGBP": "forex",
    "FRXEURJPY": "forex",
    "FRXEURCHF": "forex",
    "FRXEURAUD": "forex",
    "FRXEURCAD": "forex",
    "FRXEURNZD": "forex",
    "FRXGBPJPY": "forex",
    "FRXGBPCHF": "forex",
    "FRXGBPAUD": "forex",
    "FRXGBPCAD": "forex",
    "FRXGBPNZD": "forex",
    "FRXAUDJPY": "forex",
    "FRXAUDNZD": "forex",
    "FRXAUDCAD": "forex",
    "FRXCADJPY": "forex",
    "FRXCHFJPY": "forex",
    "FRXNZDJPY": "forex",
    "FRXUSDSGD": "forex",
    "FRXUSDHKD": "forex",
    "FRXUSDMXN": "forex",
    "FRXUSDSEK": "forex",
    "FRXUSDNOK": "forex",
    "FRXUSDDKK": "forex",
    "FRXEURSEK": "forex",
    "FRXEURNOK": "forex",
    # Commodities
    "FRXXAUUSD": "commodity",
    "XAUUSD": "commodity",
    "XAGUSD": "commodity",
    "USOIL": "commodity",
    "UKOIL": "commodity",
    "NGAS": "commodity",
    # Additional indices
    "US30":    "indices",
    "UK100":   "indices",
    "HK50":    "indices",
    # Forex exotics
    "FRXUSDZAR": "forex",
    "FRXEURTRY": "forex",
    # Equities
    "AAPL":  "equities",
    "MSFT":  "equities",
    "GOOGL": "equities",
    "META":  "equities",
    "NVDA":  "equities",
    "TSLA":  "equities",
    "AMZN":  "equities",
    "HD":    "equities",
    "JPM":   "equities",
    "V":     "equities",
    "MA":    "equities",
    "BAC":   "equities",
    "JNJ":   "equities",
    "UNH":   "equities",
    "PFE":   "equities",
    "XOM":   "equities",
    "CVX":   "equities",
    "CAT":   "equities",
    "NFLX":  "equities",
    "SBUX":  "equities",
}
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
ALLOWED_DERIV_CATEGORIES = {
    "forex", "synthetic", "commodity",
    "indices", "crypto", "stocks", "etfs",
    "equities",
}

MONITORED_CAPACITY = 50  # LEGACY — only used as fallback when universe is
# unknown. All new code must use _get_universe_capacity.
CATEGORY_MIN_SLOT_KEYS = (
    "forex", "commodity", "indices",
    "synthetic", "crypto", "equities",
)
DEFAULT_CATEGORY_MIN_SLOTS: dict[str, int] = {
    "forex":     5,
    "commodity": 3,
    "indices":   3,
    "synthetic": 5,
    "crypto":    0,
    "equities":  0,
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
    "scoring_profile": "balanced",
    "scoring_layer_weights": {
        "state_weight": 0.50,
        "opportunity_weight": 0.35,
        "structure_weight": 0.15,
    },
    "retracement_bonus": 10.0,
    "deriv_category_overrides": {},
    "enable_correlation_filter": False,
    "universe_scan_frequency": "daily",
    "active_refresh_hours": 4,
    "deep_analysis_refresh_hours": 24,
    "non_top50_analysis_depth": "global_and_prime",
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
    scoring_profile: str = Field(default="balanced")
    scoring_layer_weights: dict[str, float] = Field(default_factory=lambda: {
        "state_weight": 0.50,
        "opportunity_weight": 0.35,
        "structure_weight": 0.15,
    })
    retracement_bonus: float = Field(default=10.0, ge=0.0, le=100.0)
    deriv_category_overrides: dict[str, str] = Field(default_factory=dict)
    enable_correlation_filter: bool = False
    universe_scan_frequency: str = Field(default="daily")
    active_refresh_hours: int = Field(default=4)
    deep_analysis_refresh_hours: int = Field(default=24)
    non_top50_analysis_depth: str = Field(default="global_and_prime")
    category_min_slots: dict | None = None


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

    valid_profiles = {"aggressive", "balanced", "conservative", "custom"}
    profile = str(data.get("scoring_profile", "balanced")).lower()
    data["scoring_profile"] = (
        profile if profile in valid_profiles else "balanced"
    )

    PROFILE_WEIGHTS = {
        "aggressive": {"state": 0.40, "opportunity": 0.50, "structure": 0.10},
        "balanced": {"state": 0.50, "opportunity": 0.35, "structure": 0.15},
        "conservative": {"state": 0.30, "opportunity": 0.25, "structure": 0.45},
    }
    if profile in PROFILE_WEIGHTS:
        pw = PROFILE_WEIGHTS[profile]
        data["scoring_layer_weights"] = {
            "state_weight": pw["state"],
            "opportunity_weight": pw["opportunity"],
            "structure_weight": pw["structure"],
        }
    else:
        lw = data.get("scoring_layer_weights") or {}
        try:
            sw = float(lw.get("state_weight", 0.50))
        except (TypeError, ValueError):
            sw = 0.50
        try:
            ow = float(lw.get("opportunity_weight", 0.35))
        except (TypeError, ValueError):
            ow = 0.35
        try:
            qw = float(lw.get("structure_weight", 0.15))
        except (TypeError, ValueError):
            qw = 0.15
        sw = max(0.0, min(1.0, sw))
        ow = max(0.0, min(1.0, ow))
        qw = max(0.0, min(1.0, qw))
        wsum = sw + ow + qw
        if wsum <= 0:
            sw, ow, qw = 0.50, 0.35, 0.15
            wsum = 1.0
        data["scoring_layer_weights"] = {
            "state_weight": sw / wsum,
            "opportunity_weight": ow / wsum,
            "structure_weight": qw / wsum,
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

    valid_depths = {
        "global_only",
        "global_and_prime",
        "global_prime_walker",
        "full_chain",
    }
    depth = str(data.get("non_top50_analysis_depth", "global_and_prime"))
    data["non_top50_analysis_depth"] = (
        depth if depth in valid_depths else "global_and_prime"
    )

    try:
        deep_h = int(data.get("deep_analysis_refresh_hours", 24))
    except (TypeError, ValueError):
        deep_h = 24
    data["deep_analysis_refresh_hours"] = (
        deep_h if deep_h in {4, 8, 12, 24, 48, 72} else 24
    )

    raw_mins = data.get("category_min_slots") or {}
    slot_out: dict[str, int] = {}
    for k in CATEGORY_MIN_SLOT_KEYS:
        try:
            v = int(raw_mins.get(k, DEFAULT_CATEGORY_MIN_SLOTS[k]))
        except (TypeError, ValueError):
            v = int(DEFAULT_CATEGORY_MIN_SLOTS[k])
        slot_out[k] = max(0, min(250, v))
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
    row = db.query(ScanSettings).filter(ScanSettings.scope == "global").one_or_none()
    payload_data = payload.model_dump()
    if payload_data.get("category_min_slots") is None:
        if row is not None and isinstance(row.settings_json, dict) and "category_min_slots" in row.settings_json:
            payload_data["category_min_slots"] = row.settings_json["category_min_slots"]
        else:
            payload_data.pop("category_min_slots", None)

    normalized = _normalize_scan_settings(payload_data)
    now = datetime.now(timezone.utc)
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
        return YFINANCE_CATEGORY_MAP.get(sym, "indices")

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


STATE_BASE_SCORES: dict[str, float] = {
    "WAITING": 5.0,
    "RETRACEMENT": 25.0,
    "DEPTH_BUILDING": 30.0,
    "CHOCH_ZONE_ACTIVE": 35.0,
    "CHOCH_TESTED": 40.0,
    "CANDIDATE_ACTIVE": 45.0,
    "CANDIDATE_CHOCH_TESTED": 48.0,
    "ENTRY_ZONE": 50.0,
    "CANDIDATE_CONFIRMED": 20.0,
    "STRUCTURE_BROKEN": 5.0,
}


def _compute_hybrid_trend_score(
    result: dict[str, Any],
    settings: dict[str, Any],
    setup_row: MonitoredSetup | None = None,
) -> tuple[float, dict[str, Any]]:

    # --- Layer 1: State baseline (0-50) ---
    market_state = (
        setup_row.market_state if setup_row is not None
        else None
    ) or "WAITING"
    state_score = STATE_BASE_SCORES.get(market_state, 5.0)

    # --- Layer 2: Opportunity score (0-35) ---
    opportunity_score = 0.0
    opp_detail = "no_candidate"

    if market_state == "STRUCTURE_BROKEN":
        opportunity_score = 0.0
        opp_detail = "structure_broken"
    elif setup_row is not None and setup_row.normalised_distance_to_bos is not None:
        # normalised_distance_to_bos is already stored as
        # abs((current - bos) / global_range) * 100
        # We need ratio of journey covered:
        # 0 = just started, 1 = at BOS
        # Lower ratio = more room = higher score
        ratio = min(1.0, max(0.0,
            setup_row.normalised_distance_to_bos / 100.0
        ))
        if ratio <= 0.3:
            opportunity_score = 35.0
        elif ratio <= 0.7:
            # Linear scale from 35 down to 10
            opportunity_score = 35.0 - ((ratio - 0.3) / 0.4) * 25.0
        else:
            opportunity_score = 5.0
        opp_detail = f"ratio_{round(ratio, 2)}"
    elif market_state in ("RETRACEMENT", "DEPTH_BUILDING",
                          "CHOCH_ZONE_ACTIVE", "CHOCH_TESTED"):
        # Retracement phase — candidate not yet started
        # Good opportunity still exists
        opportunity_score = 15.0
        opp_detail = "retracement_phase"

    # --- Layer 3: Structure quality (0-15) ---
    structure_score = 0.0

    legs = [l for l in (result.get("legs") or [])
            if l.get("confirmed")]
    impulses = [l for l in legs if l.get("type") == "impulse"]
    retracements = [l for l in legs
                    if l.get("type") == "retracement"]

    # Price ratio component (0-7)
    price_ratio = 0.0
    if impulses and retracements:
        impulse_price = sum(
            abs(float(l.get("end_price", 0))
                - float(l.get("start_price", 0)))
            for l in impulses
            if l.get("end_price") is not None
        )
        retr_price = sum(
            abs(float(l.get("end_price", 0))
                - float(l.get("start_price", 0)))
            for l in retracements
            if l.get("end_price") is not None
        )
        price_ratio = impulse_price / max(retr_price, 1e-9)
        _LOG_DENOM = math.log2(11)
        price_q = min(1.0, math.log2(price_ratio + 1) / _LOG_DENOM)
        structure_score += price_q * 7.0

    # Velocity ratio component (0-4)
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
            velocities.append(
                abs(float(ep) - float(sp)) / bars
            )
        return sum(velocities) / len(velocities) \
            if velocities else 0.0

    impulse_vel = _mean_velocity(impulses)
    retr_vel = _mean_velocity(retracements)
    if retr_vel > 0:
        bar_ratio = impulse_vel / max(retr_vel, 1e-9)
        bar_q = min(1.0,
            math.log2(bar_ratio + 1) / math.log2(11)
        )
        structure_score += bar_q * 4.0

    # Leg count component (0-4)
    leg_count = len([l for l in legs if l.get("confirmed")])
    if leg_count >= 5:
        structure_score += 4.0
    elif leg_count == 4:
        structure_score += 2.0
    elif leg_count == 3:
        structure_score += 1.0

    # --- Combine with profile weights ---
    layer_weights = settings.get("scoring_layer_weights") or {
        "state_weight": 0.50,
        "opportunity_weight": 0.35,
        "structure_weight": 0.15,
    }
    sw = float(layer_weights.get("state_weight", 0.50))
    ow = float(layer_weights.get("opportunity_weight", 0.35))
    qw = float(layer_weights.get("structure_weight", 0.15))

    # Normalise each layer to 0-100 before weighting
    state_norm = (state_score / 50.0) * 100.0
    opp_norm = (opportunity_score / 35.0) * 100.0
    struct_norm = (structure_score / 15.0) * 100.0

    total = min(100.0, max(0.0,
        state_norm * sw +
        opp_norm * ow +
        struct_norm * qw
    ))

    return total, {
        "state_score": round(state_score, 2),
        "opportunity_score": round(opportunity_score, 2),
        "structure_score": round(structure_score, 2),
        "market_state": market_state,
        "price_ratio": round(price_ratio, 4),
        "opp_detail": opp_detail,
        "profile": settings.get("scoring_profile", "balanced"),
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
        "display_name": get_display_name(setup.symbol),
        "sector": get_sector(setup.symbol),
        "universe": setup.universe or _infer_universe(setup.symbol),
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
        "market_state": setup.market_state or "WAITING",
        "is_monitored": True,
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
        "display_name": get_display_name(symbol),
        "sector": get_sector(symbol),
        "universe": _infer_universe(symbol),
        "timeframe": timeframe,
        "trend": "range",
        "current_phase": None,
        "fsm_state": "WAITING",
        "market_state": None,
        "ema_signal": "WAITING",
        "trend_score": 0.0,
        "pullback_depth": 0,
        "total_mitigation_count": 0,
        "waiting_for": "",
        "active_choch_zone": None,
        "active_bos": None,
        "active_zones": [],
        "mtf_alignment": {},
        "structural_state": {},
        "structural_state_json": {},
        "score_components": None,
        "last_checked_at": now_iso,
        "created_at": None,
        "universe_rank": None,
        "is_monitored": False,
    }


def _enrich_placeholder_from_cached_state(
    placeholder: dict[str, Any],
    symbol: str,
    db: Session,
) -> dict[str, Any]:
    """Best-effort enrichment for unmonitored symbols from cached analysis tables."""
    sym = symbol.strip().upper()

    gsc = (
        db.query(GlobalStructureCache)
        .filter(GlobalStructureCache.symbol == sym)
        .one_or_none()
    )
    if gsc is not None:
        trend = (gsc.trend_direction or "").strip().lower()
        if trend in {"up", "down", "range"}:
            placeholder["trend"] = trend
        if gsc.market_state:
            placeholder["market_state"] = gsc.market_state
        if gsc.computed_at is not None:
            placeholder["last_checked_at"] = gsc.computed_at.isoformat()
        if gsc.legs_json:
            placeholder["structural_state_json"] = {
                "legs": gsc.legs_json,
            }
            placeholder["structural_state"] = placeholder["structural_state_json"]

    us = (
        db.query(UniverseScore)
        .filter(UniverseScore.symbol == sym)
        .one_or_none()
    )
    if us is not None:
        placeholder["universe_rank"] = us.universe_rank
        placeholder["trend_score"] = float(us.total_score or 0.0)

    cic = (
        db.query(CandidateImpulseCache)
        .filter(CandidateImpulseCache.symbol == sym)
        .one_or_none()
    )
    if cic is not None:
        if placeholder.get("market_state") is None:
            placeholder["market_state"] = "CANDIDATE_ACTIVE"
        placeholder["fsm_state"] = "CANDIDATE_ACTIVE"
        if isinstance(cic.candidate_walker_json, dict):
            placeholder["structural_state_json"] = cic.candidate_walker_json
            placeholder["structural_state"] = cic.candidate_walker_json
            placeholder["pullback_depth"] = int(
                cic.candidate_walker_json.get("max_depth_reached", 0) or 0
            )
            placeholder["total_mitigation_count"] = int(
                cic.candidate_walker_json.get("total_mitigation_count", 0) or 0
            )
            placeholder["waiting_for"] = str(
                cic.candidate_walker_json.get("waiting_for", "") or ""
            )
        if cic.computed_at is not None:
            placeholder["last_checked_at"] = cic.computed_at.isoformat()

    return placeholder


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


SYNTHETIC_UNIVERSE_PREFIXES = (
    "R_", "1HZ", "BOOM", "CRASH", "JD",
    "OTC_", "STEP", "WLD", "RB", "RDBULL",
    "STPRNG",
)


def _infer_universe(symbol: str) -> str:
    """
    Route a symbol to its universe.
    multi_asset: forex, indices, commodity, equities
    synthetic: Deriv synthetic indices
    crypto: Binance crypto pairs
    """
    sym = symbol.strip().upper()
    if sym.endswith("USDT") or sym.endswith("BTC") or sym.endswith("ETH"):
        return "crypto"
    for prefix in SYNTHETIC_UNIVERSE_PREFIXES:
        if sym.startswith(prefix):
            return "synthetic"
    cat = _infer_category(sym)
    if cat == "synthetic":
        return "synthetic"
    if cat == "crypto":
        return "crypto"
    return "multi_asset"


def _get_universe_settings(
    universe_name: str,
    db: Session,
) -> UniverseSettings | None:
    return (
        db.query(UniverseSettings)
        .filter(UniverseSettings.universe_name == universe_name)
        .first()
    )


def _get_universe_capacity(
    universe_name: str,
    db: Session,
) -> int:
    us = _get_universe_settings(universe_name, db)
    if us is not None:
        return us.capacity
    defaults = {
        "multi_asset": 150,
        "synthetic": 50,
        "crypto": 50,
    }
    return defaults.get(universe_name, 50)


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
    if cat in ("equities", "stocks"):
        return "EQUITIES"
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
                universe=_infer_universe(symbol),
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
        sym_universe = _infer_universe(symbol)
        _evict_to_capacity(
            db,
            capacity=_get_universe_capacity(sym_universe, db),
            universe=sym_universe,
        )


def _write_score_and_state(
    setup_row: MonitoredSetup,
    new_score: float | None,
    score_components: dict[str, Any] | None,
    market_state: str | None,
    db: Session,
) -> bool:
    """Atomically persist ``trend_score`` and ``market_state`` together.

    If no score was computed, the helper refuses to write.
    If market state is unavailable, it writes the score and keeps the
    existing market_state unchanged.

    Returns ``True`` on successful commit, ``False`` otherwise.
    """
    if new_score is None:
        logger.warning(
            "_write_score_and_state: no score "
            "computed for %s — skipping write "
            "entirely to prevent corruption",
            setup_row.symbol,
        )
        return False

    # market_state can be None — in that case
    # we write the score but keep the existing
    # market_state on the row unchanged.
    # This prevents the score from being stuck
    # at 0.0 just because state computation failed.
    if market_state is None:
        logger.warning(
            "_write_score_and_state: no market "
            "state computed for %s — writing score only, "
            "keeping existing state: %s",
            setup_row.symbol,
            setup_row.market_state,
        )

    now = datetime.now(timezone.utc)
    try:
        setup_row.trend_score = new_score
        # score_components_json is not part of the current ORM model —
        # the existing pipeline discards ``score_components``. Guard with
        # ``hasattr`` so the helper picks it up automatically if the
        # column is ever added.
        if hasattr(setup_row, "score_components_json"):
            setup_row.score_components_json = score_components or {}
        # Only update market_state when computed
        if market_state is not None:
            setup_row.market_state = market_state
        setup_row.last_checked_at = now
        setup_row.updated_at = now
        db.commit()
        return True
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning(
            "_write_score_and_state failed for %s: %s",
            setup_row.symbol,
            e,
        )
        return False


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
    """Bootstrap a symbol into monitored_setups.

    Only call this from explicit addition paths (rank universe jobs,
    manual add via POST /api/setups/monitor/{symbol}).
    DO NOT call this from browsing/view paths — that would silently
    inflate the monitored universe on every page view.

    On-demand stage 1: persist MonitoredSetup or record failure.
    Does not evict other rows.
    """
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
    universe: str | None = None,
) -> None:
    if settings is None:
        settings = _get_effective_scan_settings(db)
    else:
        settings = _normalize_scan_settings(settings)
    if universe is not None:
        us = _get_universe_settings(universe, db)
        if us is not None and us.category_min_slots_json:
            merged = dict(
                settings.get("category_min_slots")
                or dict(DEFAULT_CATEGORY_MIN_SLOTS)
            )
            for k, v in (us.category_min_slots_json or {}).items():
                try:
                    merged[k] = int(v)
                except (TypeError, ValueError):
                    pass
            settings = {**settings, "category_min_slots": merged}
    mins: dict[str, int] = settings.get("category_min_slots") or dict(DEFAULT_CATEGORY_MIN_SLOTS)

    sql_select = """
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
    """
    if universe is not None:
        sql_select += "                WHERE ms.universe = :univ\n"
        rows = list(
            db.execute(
                text(sql_select + "                ORDER BY ms.trend_score DESC, ms.id ASC"),
                {"univ": universe},
            ).mappings().all()
        )
    else:
        rows = list(
            db.execute(
                text(
                    sql_select
                    + "                ORDER BY ms.trend_score DESC, ms.id ASC"
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


def _run_scan_sync(
    request: ScanRequest,
    settings: dict[str, Any] | None = None,
    universe_filter: str | None = None,
) -> None:
    db = SessionLocal()
    # Observability hooks — populated throughout the job and flushed
    # to ScanJobLog in the finally block below.
    _scan_log_start = datetime.now(timezone.utc)
    _scan_log_error: str | None = None
    try:
        effective_settings = _normalize_scan_settings(settings or DEFAULT_SCAN_SETTINGS)
        if universe_filter is not None:
            us_row = _get_universe_settings(universe_filter, db)
            if us_row is not None and us_row.category_min_slots_json:
                merged = dict(
                    effective_settings.get("category_min_slots")
                    or dict(DEFAULT_CATEGORY_MIN_SLOTS)
                )
                for k, v in (us_row.category_min_slots_json or {}).items():
                    try:
                        merged[k] = int(v)
                    except (TypeError, ValueError):
                        pass
                effective_settings = {
                    **effective_settings,
                    "category_min_slots": merged,
                }
        symbols = _normalize_symbol_list(request.symbols)
        deriv_active_symbols: set[str] | None = None

        # Refresh only monitored symbols — do NOT discover new ones
        if not symbols:
            rows = db.query(MonitoredSetup.symbol, MonitoredSetup.universe).all()
            sym_univ: dict[str, str | None] = {}
            for sym, univ in rows:
                s = str(sym)
                if s not in sym_univ:
                    sym_univ[s] = univ
            if universe_filter is not None:
                symbols = sorted(
                    s
                    for s, univ in sym_univ.items()
                    if (univ or _infer_universe(s)) == universe_filter
                )
            else:
                symbols = sorted(sym_univ.keys())
            if not symbols:
                logger.info("No monitored symbols to refresh")
                return

            logger.info("Refreshing %d monitored symbols", len(symbols))
            # Skip initial eviction — already within capacity,
            # only processing existing monitored setups.
            # Final Stage 3 eviction is safety net.

        _scan_status["in_progress"] = True
        _scan_status["stage"] = "stage1"
        _scan_status["total_symbols"] = len(symbols)
        _scan_status["stage1_complete"] = 0
        _scan_status["stage2_complete"] = 0
        _scan_status["stage2_total"] = 0
        _scan_status["started_at"] = datetime.now(timezone.utc).isoformat()
        _scan_status["completed_at"] = None
        _scan_status["last_error"] = None
        _scan_status["paper_engine"] = None

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
        deep_refresh_hours = int(effective_settings.get("deep_analysis_refresh_hours", 24))
        universe_capacity = (
            _get_universe_capacity(universe_filter, db)
            if universe_filter is not None
            else _get_universe_capacity(universe_filter or "multi_asset", db)
        )
        top50_rows_query = (
            db.query(MonitoredSetup)
            .order_by(MonitoredSetup.trend_score.desc(), MonitoredSetup.id.asc())
        )
        if universe_filter is not None:
            ordered = top50_rows_query.all()
            top50_rows = [
                m
                for m in ordered
                if (m.universe or _infer_universe(m.symbol)) == universe_filter
            ][:universe_capacity]
        else:
            top50_rows = top50_rows_query.limit(universe_capacity).all()
        top50_symbols = [r.symbol for r in top50_rows]
        _gsc_batch = {
            row.symbol: row
            for row in db.query(GlobalStructureCache).filter(
                GlobalStructureCache.symbol.in_(top50_symbols)
            ).all()
        }
        _scan_status["stage2_total"] = len(top50_symbols)
        logger.info(
            "Stage 2: targeted deep refresh for %d top-50 monitored symbols",
            len(top50_symbols),
        )

        ACTIVE_REFRESH_TIMEFRAMES = ["15m", "30m", "1h", "4h", "1d"]
        now = datetime.now(timezone.utc)

        for symbol in top50_symbols:
            with _stage2_semaphore:
                sym_db = SessionLocal()
                try:
                    # 1. Refresh candles for active timeframes only
                    for tf in ACTIVE_REFRESH_TIMEFRAMES:
                        try:
                            refresh_candles(symbol, tf, sym_db)
                        except Exception as e:
                            logger.warning("Stage 2 candle refresh %s %s: %s", symbol, tf, e)

                    # 2. Staleness check for deep analysis
                    gsc_row = _gsc_batch.get(symbol)
                    needs_deep = gsc_row is None or gsc_row.computed_at is None
                    if not needs_deep:
                        computed_at_utc = gsc_row.computed_at
                        if computed_at_utc.tzinfo is None:
                            computed_at_utc = computed_at_utc.replace(tzinfo=timezone.utc)
                        needs_deep = (now - computed_at_utc).total_seconds() > deep_refresh_hours * 3600

                    if needs_deep:
                        try:
                            recompute_full_chain_for_symbol(symbol, sym_db, layers=None)
                        except Exception as e:
                            logger.warning("Stage 2 full recompute %s: %s", symbol, e)
                    else:
                        try:
                            recompute_full_chain_for_symbol(symbol, sym_db, layers=["candidate"])
                        except Exception as e:
                            logger.warning("Stage 2 candidate recompute %s: %s", symbol, e)

                    # 4+5. Atomically compute market_state and trend_score,
                    # then persist both together via _write_score_and_state.
                    # Either both values land on the row or neither does — no
                    # more score=0 / state=CANDIDATE_ACTIVE divergence.
                    setup_row = _get_setup_by_symbol(sym_db, symbol)
                    gsc_updated = _gsc_batch.get(symbol)

                    computed_state: str | None = None
                    computed_score: float | None = None
                    computed_components: dict[str, Any] = {}

                    try:
                        from src.scanner.global_structure import (
                            compute_market_state,
                        )

                        computed_state = compute_market_state(symbol, sym_db)
                    except Exception as e:  # noqa: BLE001
                        logger.warning(
                            "Market state compute failed %s: %s", symbol, e
                        )

                    if setup_row is not None and gsc_updated is not None:
                        try:
                            # Reflect the just-computed state on the in-memory
                            # row so _compute_hybrid_trend_score (which reads
                            # setup_row.market_state) uses the fresh value.
                            # Not yet persisted — _write_score_and_state
                            # commits both fields below, or rolls back.
                            if computed_state is not None:
                                setup_row.market_state = computed_state

                            synthetic_result = {
                                "legs": gsc_updated.legs_json or [],
                                "current_phase": setup_row.current_phase,
                            }
                            computed_score, computed_components = (
                                _compute_hybrid_trend_score(
                                    synthetic_result,
                                    effective_settings,
                                    setup_row,
                                )
                            )
                        except Exception as e:  # noqa: BLE001
                            logger.warning(
                                "Score compute failed %s: %s", symbol, e
                            )

                    if (
                        setup_row is not None
                        and computed_score is not None
                    ):
                        _write_score_and_state(
                            setup_row,
                            computed_score,
                            computed_components,
                            computed_state,
                            sym_db,
                        )
                        # Propagate the new state to GlobalStructureCache and
                        # log the transition in MarketStateHistory. Failures
                        # here do not roll back the row write above.
                        if computed_state is not None:
                            try:
                                from src.scanner.global_structure import (
                                    write_market_state,
                                )

                                write_market_state(
                                    symbol,
                                    computed_state,
                                    sym_db,
                                    score=computed_score,
                                    trend_score=computed_score,
                                )
                            except Exception as e:  # noqa: BLE001
                                logger.warning(
                                    "write_market_state failed %s: %s", symbol, e
                                )
                        # Invalidate the analysis cache so the
                        # next market view request gets fresh data
                        # reflecting the updated score and state.
                        # This closes the gap where the 4-hour
                        # refresh updated structure but the cache
                        # still served old analysis for up to 4h.
                        try:
                            from src.api.routers.analysis import (
                                on_structure_updated,
                            )
                            on_structure_updated(symbol, sym_db)
                        except Exception as e:
                            logger.warning(
                                "Stage 2: cache invalidation "
                                "failed for %s: %s", symbol, e
                            )

                    _scan_status["stage2_complete"] += 1
                    logger.info("Stage 2 complete: %s", symbol)
                except Exception as e:  # noqa: BLE001
                    logger.warning("Stage 2 failed for %s: %s", symbol, e)
                finally:
                    sym_db.close()

        # Stage 3a — correlation filter (allowed to fail without blocking eviction)
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
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Stage 3 correlation failed (continuing to eviction): %s", e
            )

        # Stage 3b — paper engine (allowed to fail without blocking eviction)
        try:
            _scan_status["stage"] = "stage3_paper"
            from src.execution.paper_engine import run_paper_engine

            paper_result = run_paper_engine(
                db, universe=universe_filter
            )
            _scan_status["paper_engine"] = paper_result
            if paper_result.get("error"):
                logger.warning(
                    "Paper engine commit failed: %s",
                    paper_result["error"],
                )
            else:
                logger.info(
                    "Paper engine: checked=%d closed_tp=%d "
                    "closed_sl=%d new_trades=%d",
                    paper_result["monitor"]["checked"],
                    paper_result["monitor"]["closed_tp"],
                    paper_result["monitor"]["closed_sl"],
                    paper_result["new_trades_opened"],
                )
        except Exception as _pe:
            logger.warning(
                "Stage 3 paper engine failed (continuing to eviction): %s", _pe
            )

        # Stage 3c — eviction ALWAYS runs. Must not share a try/except with
        # correlation or paper engine so a failure there cannot silently skip
        # capacity enforcement.
        try:
            _scan_status["stage"] = "stage3_eviction"
            _evict_to_capacity(
                db,
                capacity=universe_capacity,
                settings=effective_settings,
                universe=universe_filter,
            )
            _scan_status["stage"] = "complete"
        except Exception as e:  # noqa: BLE001
            logger.warning("Stage 3 eviction failed: %s", e)
            _scan_status["stage"] = "eviction_failed"
            _scan_status["last_error"] = str(e)
    except Exception as e:  # noqa: BLE001
        logger.exception("Background scan failed: %s", e)
        _scan_status["stage"] = "failed"
        _scan_status["last_error"] = str(e)
        _scan_log_error = str(e)[:2000]
    finally:
        _scan_status["in_progress"] = False
        _scan_status["completed_at"] = datetime.now(timezone.utc).isoformat()
        # Write refresh-job result to ScanJobLog using a fresh session
        # so partially-rolled-back state on `db` never blocks the write.
        try:
            from src.scanner.job_log import write_job_log

            log_db = SessionLocal()
            try:
                now_utc = datetime.now(timezone.utc)
                duration = (now_utc - _scan_log_start).total_seconds()
                stage2_attempted = int(
                    _scan_status.get("stage2_total") or 0
                )
                stage2_completed = int(
                    _scan_status.get("stage2_complete") or 0
                )
                write_job_log(
                    log_db,
                    job_type="universe_refresh",
                    started_at=_scan_log_start,
                    completed_at=now_utc,
                    duration_seconds=duration,
                    # total_symbols = how many were in the
                    # Stage 2 processing queue (not just
                    # how many exist in the universe)
                    total_symbols=stage2_attempted,
                    success_count=stage2_completed,
                    failure_count=max(
                        0, stage2_attempted - stage2_completed
                    ),
                    status="failed" if _scan_log_error else "completed",
                    error_message=_scan_log_error,
                    universe_name=universe_filter,
                )
            finally:
                log_db.close()
        except Exception as log_exc:  # noqa: BLE001
            logger.warning(
                "Failed to write refresh job log: %s", log_exc
            )
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


# ---------------------------------------------------------------------------
# /api/setups/universe response cache
# ---------------------------------------------------------------------------
# Building the full universe payload is expensive (~5-6s) because it rebuilds
# placeholders across every broker-config symbol and enriches each row with
# readiness + ranking fields. Cache the serialized list in-process for a few
# minutes; invalidate on ranking completion so fresh scores surface promptly.
#
# NOTE: a separate module-level `_universe_cache` above this block caches the
# *Binance top-symbols set* and must not be confused with the endpoint cache
# below — they are orthogonal.
_universe_endpoint_cache: dict[str, Any] = {
    "data": None,
    "built_at": None,
}
_universe_endpoint_cache_lock = threading.Lock()
_UNIVERSE_ENDPOINT_CACHE_TTL_SECONDS = 300


def invalidate_universe_cache() -> None:
    """Drop the cached /api/setups/universe payload.

    Call after ranking / promotions / monitored-setup mutations so the next
    request rebuilds with fresh data.
    """
    with _universe_endpoint_cache_lock:
        _universe_endpoint_cache["data"] = None
        _universe_endpoint_cache["built_at"] = None
    logger.info("universe_cache invalidated")


@router.get("/universe")
def list_setups_universe(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """
    Return full universe rows:
    - all Deriv symbols from config/symbols.yaml
    - top 350 Binance symbols by volume
    Includes placeholders when no monitored setup exists yet.
    Each row includes readiness_state (FULL / PARTIAL / ERROR / UNSCANNED).

    Response is cached in-process for
    :data:`_UNIVERSE_ENDPOINT_CACHE_TTL_SECONDS` seconds and invalidated by
    :func:`invalidate_universe_cache` after ranking runs.
    """
    now = datetime.now(timezone.utc)

    with _universe_endpoint_cache_lock:
        cached_data = _universe_endpoint_cache["data"]
        built_at = _universe_endpoint_cache["built_at"]

    if (
        cached_data is not None
        and built_at is not None
        and (now - built_at).total_seconds() < _UNIVERSE_ENDPOINT_CACHE_TTL_SECONDS
    ):
        return cached_data

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

    with _universe_endpoint_cache_lock:
        _universe_endpoint_cache["data"] = payload
        _universe_endpoint_cache["built_at"] = now

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


@router.post("/refresh-yfinance-candles")
def refresh_yfinance_candles(
    db: Session = Depends(get_db)
) -> dict[str, Any]:
    """
    Trigger full candle refresh for all yfinance symbols
    including newly mapped forex/commodity symbols.
    Runs in background thread.
    """
    from src.adapters.yfinance_data import YFINANCE_SYMBOL_MAP

    _ = db
    symbols = list(YFINANCE_SYMBOL_MAP.keys())
    all_tfs = ["1d", "1w", "4h", "1h", "30m", "15m"]

    def _refresh_all() -> None:
        db2 = SessionLocal()
        try:
            def _refresh_sym(sym: str) -> None:
                db3 = SessionLocal()
                try:
                    for tf in all_tfs:
                        try:
                            refresh_candles(sym, tf, db3, force_full=True)
                        except Exception as e:  # noqa: BLE001
                            logger.warning(
                                "yfinance refresh %s %s: %s",
                                sym,
                                tf,
                                e,
                            )
                finally:
                    db3.close()

            with ThreadPoolExecutor(max_workers=5) as ex:
                list(ex.map(_refresh_sym, symbols))
            logger.info(
                "yfinance candle refresh complete: %d symbols",
                len(symbols),
            )
        finally:
            db2.close()

    threading.Thread(target=_refresh_all, daemon=True).start()
    return {
        "status": "refresh_started",
        "symbols": len(symbols),
    }


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


@router.get("/{symbol}/state-history")
def get_state_history(
    symbol: str,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[dict]:
    from src.db.models import MarketStateHistory
    rows = (
        db.query(MarketStateHistory)
        .filter(MarketStateHistory.symbol == symbol.strip().upper())
        .order_by(MarketStateHistory.transitioned_at.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "state": r.state,
            "previous_state": r.previous_state,
            "transitioned_at": r.transitioned_at.isoformat(),
            "score": r.score,
            "trend_score": r.trend_score,
            "notes": r.notes,
        }
        for r in rows
    ]


@router.get("/{symbol}")
def get_setup(symbol: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    normalized = symbol.strip().upper()
    setup = _get_setup_by_symbol(db, normalized)
    if setup is None:
        # Unmonitored symbol: return a read-only placeholder built from
        # whatever cached analysis is already available. We deliberately
        # do NOT bootstrap a MonitoredSetup row here — browsing must not
        # mutate the monitored universe. Use POST /api/setups/monitor/{symbol}
        # to add a symbol explicitly.
        placeholder = _serialize_placeholder_setup(normalized, timeframe="1d")
        placeholder = _enrich_placeholder_from_cached_state(
            placeholder, normalized, db
        )
        idx = build_readiness_index(db, [normalized]).get(normalized, {})
        merge_readiness_fields(placeholder, idx)
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


@router.post("/monitor/{symbol}")
def add_to_monitoring(
    symbol: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Explicitly add a symbol to monitored_setups.

    This is the ONLY request path that may create a new MonitoredSetup
    row outside of rank universe jobs. Browsing via GET /api/setups/{symbol}
    does not bootstrap rows — callers must opt in through this endpoint.
    """
    sym = symbol.strip().upper()

    existing = (
        db.query(MonitoredSetup)
        .filter(MonitoredSetup.symbol == sym)
        .first()
    )
    if existing is not None:
        return {
            "status": "already_monitored",
            "symbol": sym,
        }

    universe = _infer_universe(sym)
    cap = _get_universe_capacity(universe, db)
    current_count = (
        db.query(MonitoredSetup)
        .filter(MonitoredSetup.universe == universe)
        .count()
    )
    if current_count >= cap:
        return {
            "status": "at_capacity",
            "symbol": sym,
            "universe": universe,
            "capacity": cap,
            "current": current_count,
        }

    result = _bootstrap_stage1_symbol(db, sym, "1h")
    if result is None:
        return {
            "status": "bootstrap_failed",
            "symbol": sym,
        }
    return {
        "status": "added",
        "symbol": sym,
        "universe": universe,
    }


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
    _scan_status["paper_engine"] = None

    request_copy = ScanRequest(**request.model_dump())

    def _run_scan_then_cleanup() -> None:
        try:
            _run_scan_sync(request_copy, effective_settings)
        finally:
            # Manual scan: enforce per-universe capacity since _run_scan_sync
            # with universe_filter=None may use the legacy global cap.
            db_cleanup = SessionLocal()
            try:
                us_rows = (
                    db_cleanup.query(UniverseSettings)
                    .filter(UniverseSettings.is_active == True)  # noqa: E712
                    .all()
                )
                for us in us_rows:
                    _evict_to_capacity(
                        db_cleanup,
                        capacity=us.capacity,
                        universe=us.universe_name,
                    )
                logger.info(
                    "Manual scan: per-universe eviction complete"
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Manual scan per-universe eviction failed: %s", e
                )
            finally:
                db_cleanup.close()

    worker = threading.Thread(target=_run_scan_then_cleanup, daemon=True)
    worker.start()

    return {
        "status": "scan_started",
        "total_symbols": estimated_count,
    }