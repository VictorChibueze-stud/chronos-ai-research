"""Full-universe HTF ranking job: weekly/daily trend, score, persist, promote top 50."""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from src.adapters.binance_data import fetch_binance_ohlc_sync
from src.adapters.deriv_data import fetch_deriv_ohlc_sync, get_active_deriv_symbols
from src.adapters.yfinance_data import fetch_yfinance_ohlc_sync, is_yfinance_symbol
from src.core.filter_defaults import SCAN_AND_ANALYSIS_FILTER_DEFAULTS
from src.core.trend_id import identify_trend
from src.api.routers.setups import _infer_universe
from src.db.models import GlobalStructureCache, MonitoredSetup, UniverseScore
from src.db.session import SessionLocal
from src.scanner.analysis_job_state import get_analysis_job_flags
from src.scanner.job_log import write_job_log
from src.scanner.market_scanner import (
    DERIV_COMMODITY_SYMBOLS,
    DERIV_FOREX_SYMBOLS,
    DERIV_INDICES_SYMBOLS,
    fetch_top_symbols,
)

logger = logging.getLogger(__name__)

from sqlalchemy import text

_SYMBOLS_CFG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "symbols.yaml"
_TF_WINDOWS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "timeframe_windows.yaml"

_ranking_status: dict[str, Any] = {
    "in_progress": False,
    "total_symbols": 0,
    "symbols_scored": 0,
    "current_symbol": None,
    "started_at": None,
    "completed_at": None,
    "last_error": None,
    "estimated_seconds_remaining": None,
}

_ranking_lock = threading.Lock()

_CATEGORY_MIN_SLOT_KEYS = (
    "forex", "commodity", "indices", "synthetic", "crypto", "equities",
)


def _filter_universe_symbols(
    symbols: list[str],
    universe: str,
) -> list[str]:
    """Filter symbol list to only those belonging to the given universe."""
    return [s for s in symbols if _infer_universe(s) == universe]
_SYNTHETIC_PREFIXES = ("R_", "1HZ", "BOOM", "CRASH", "JD", "OTC_", "STEP", "WLD")


def _load_lookback_days(interval: str) -> float:
    try:
        with open(_TF_WINDOWS_PATH, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        tfs = cfg.get("timeframes", {})
        if interval in tfs and "lookback_days" in tfs[interval]:
            return float(tfs[interval]["lookback_days"])
    except Exception:
        pass
    defaults = {"1d": 2190.0, "1w": 3650.0}
    return defaults.get(interval, 2190.0)


def _is_binance_symbol(symbol: str) -> bool:
    u = symbol.upper()
    return u.endswith("USDT") or u.endswith("BTC")


def build_ranking_universe(top_n: int = 350) -> list[str]:
    """Binance top-N + Deriv config/active/hardcoded lists (mirrors warm-cache universe)."""
    symbols_data: dict[str, Any] = {}
    if _SYMBOLS_CFG_PATH.exists():
        try:
            with open(_SYMBOLS_CFG_PATH, encoding="utf-8") as fh:
                symbols_data = yaml.safe_load(fh) or {}
        except Exception as exc:
            logger.warning("Failed to load symbols.yaml: %s", exc)

    deriv_yaml = [str(code) for code in (symbols_data.get("deriv") or {}).values()]
    try:
        binance = fetch_top_symbols(n=top_n)
    except Exception as exc:
        logger.warning("Binance universe fetch failed: %s", exc)
        binance = []

    try:
        deriv_active = list(get_active_deriv_symbols())
    except Exception as exc:
        logger.warning("Deriv active symbols failed: %s", exc)
        deriv_active = []

    merged = (
        set(binance)
        | set(deriv_yaml)
        | set(deriv_active)
        | set(DERIV_FOREX_SYMBOLS)
        | set(DERIV_COMMODITY_SYMBOLS)
        | set(DERIV_INDICES_SYMBOLS)
    )
    return sorted(merged)


def _fetch_htf_candles(symbol: str, timeframe: str, active_deriv: set[str]) -> list[Any]:
    start = datetime.now(timezone.utc) - timedelta(days=_load_lookback_days(timeframe))
    if _is_binance_symbol(symbol):
        return fetch_binance_ohlc_sync(symbol, timeframe, start_time=start)
    if is_yfinance_symbol(symbol):
        return fetch_yfinance_ohlc_sync(symbol, timeframe, start_time=start)
    return fetch_deriv_ohlc_sync(
        symbol,
        timeframe,
        start_time=start,
        active_symbols=active_deriv,
        validate_active_symbol=True,
    )


def _confirmed_leg_count(legs: list[dict[str, Any]]) -> int:
    return sum(1 for leg in legs if leg.get("confirmed") is True)


def _serialize_legs(legs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for leg in legs:
        d: dict[str, Any] = {}
        for k, v in leg.items():
            if k in (
                "type",
                "start_price",
                "end_price",
                "start_index",
                "end_index",
                "confirmed",
                "slope",
            ):
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
                else:
                    d[k] = v
        out.append(d)
    return out


def _prune_non_top_setups(
    db,
    keep_symbols: set[str],
    universe_name: str | None = None,
) -> None:
    if not keep_symbols:
        return

    rows = list(
        db.execute(
            text(
                """
                SELECT ms.id, ms.symbol, ms.universe,
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
            )
        ).mappings().all()
    )

    to_delete_ids: list[int] = []
    for r in rows:
        if bool(r["is_protected"]):
            continue
        sym_u = str(r["symbol"]).upper()
        if sym_u in keep_symbols:
            continue
        if universe_name is not None:
            ucol = r.get("universe")
            if (ucol or _infer_universe(sym_u)) != universe_name:
                continue
        to_delete_ids.append(int(r["id"]))
    if not to_delete_ids:
        return

    deleted = (
        db.query(MonitoredSetup)
        .filter(MonitoredSetup.id.in_(to_delete_ids))
        .all()
    )
    for setup in deleted:
        logger.info(
            "Ranking prune: removing stale setup %s (score=%.1f)",
            setup.symbol,
            setup.trend_score,
        )
        db.delete(setup)
    db.commit()


def compute_ranking_metrics(result: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
    """Impulse ratios, components, base_score, total_score (before min-legs zeroing)."""
    legs = [l for l in (result.get("legs") or []) if l.get("confirmed") is True]
    impulses = [l for l in legs if l.get("type") == "impulse" and l.get("end_price") is not None]
    retracements = [l for l in legs if l.get("type") == "retracement" and l.get("end_price") is not None]

    confirmed_count = len(legs)
    if confirmed_count < 2:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

    impulse_price = sum(
        abs(float(l.get("end_price", 0)) - float(l.get("start_price", 0))) for l in impulses
    )
    retr_price = sum(
        abs(float(l.get("end_price", 0)) - float(l.get("start_price", 0))) for l in retracements
    )
    impulse_price_ratio = impulse_price / max(retr_price, 1e-9)

    def _candle_span(leg: dict[str, Any]) -> int:
        try:
            return max(1, int(leg.get("end_index", 0)) - int(leg.get("start_index", 0)))
        except (TypeError, ValueError):
            return 1

    imp_vels = [
        abs(float(l.get("end_price", 0)) - float(l.get("start_price", 0))) / _candle_span(l)
        for l in impulses
    ]
    retr_vels = [
        abs(float(l.get("end_price", 0)) - float(l.get("start_price", 0))) / _candle_span(l)
        for l in retracements
    ]

    mean_imp_v = sum(imp_vels) / len(imp_vels) if imp_vels else 0.0
    mean_retr_v = sum(retr_vels) / len(retr_vels) if retr_vels else 0.0
    impulse_velocity_ratio = mean_imp_v / max(mean_retr_v, 1e-9)

    _LOG_DENOM = math.log2(11)
    price_component = min(100.0, max(0.0, (math.log2(impulse_price_ratio + 1) / _LOG_DENOM) * 100.0))
    velocity_component = min(100.0, max(0.0, (math.log2(impulse_velocity_ratio + 1) / _LOG_DENOM) * 100.0))
    base_score = (price_component * 0.7) + (velocity_component * 0.3)

    retracement_bonus = 15.0 if (result.get("current_phase") == "retracement") else 0.0
    candidate_impulse_bonus = 0.0

    total_score = min(100.0, base_score + retracement_bonus + candidate_impulse_bonus)
    return impulse_price_ratio, impulse_velocity_ratio, price_component, velocity_component, base_score, total_score


def _promotion_category(symbol: str) -> str:
    sym = symbol.upper()
    if sym.endswith("USDT") or sym.endswith("BTC"):
        return "crypto"
    from src.adapters.yfinance_data import YFINANCE_SECTOR_MAP
    if sym in YFINANCE_SECTOR_MAP:
        return "equities"
    if sym in set(DERIV_FOREX_SYMBOLS) or sym.startswith("FRX"):
        return "forex"
    if is_yfinance_symbol(sym) or sym in {"SPX500", "NAS100", "DAX40", "FTSE100", "NKY225", "GER40", "UK100", "JP225"}:
        return "indices"
    if sym in set(DERIV_COMMODITY_SYMBOLS):
        return "commodity"
    if sym in set(DERIV_INDICES_SYMBOLS):
        return "indices"
    if any(sym.startswith(prefix) for prefix in _SYNTHETIC_PREFIXES):
        return "synthetic"
    return "other"


def _select_top_with_category_mins(
    sorted_rows: list[dict[str, Any]],
    capacity: int,
    mins: dict[str, int],
) -> list[dict[str, Any]]:
    if len(sorted_rows) <= capacity:
        return list(sorted_rows)

    selected = list(sorted_rows[:capacity])
    selected_symbols = {str(r["symbol"]).upper() for r in selected}

    def _counts(rows: list[dict[str, Any]]) -> Counter[str]:
        return Counter(_promotion_category(str(r["symbol"])) for r in rows)

    counts = _counts(selected)
    max_swaps = max(capacity * 10, 100)

    for _ in range(max_swaps):
        deficit_category: str | None = None
        for ckey in _CATEGORY_MIN_SLOT_KEYS:
            need = int(mins.get(ckey, 0))
            if need > 0 and counts.get(ckey, 0) < need:
                deficit_category = ckey
                break
        if deficit_category is None:
            break

        outsider: dict[str, Any] | None = None
        for row in sorted_rows:
            sym = str(row["symbol"]).upper()
            if sym in selected_symbols:
                continue
            if _promotion_category(sym) == deficit_category:
                outsider = row
                break
        if outsider is None:
            logger.warning(
                "Promotion mins: unable to satisfy %r minimum; no outsider available",
                deficit_category,
            )
            break

        insider_index: int | None = None
        for i in range(len(selected) - 1, -1, -1):
            cat = _promotion_category(str(selected[i]["symbol"]))
            if counts.get(cat, 0) > int(mins.get(cat, 0)):
                insider_index = i
                break
        if insider_index is None:
            logger.warning(
                "Promotion mins: unable to satisfy %r minimum; no swappable insider",
                deficit_category,
            )
            break

        removed = selected[insider_index]
        selected[insider_index] = outsider
        selected_symbols.remove(str(removed["symbol"]).upper())
        selected_symbols.add(str(outsider["symbol"]).upper())
        counts = _counts(selected)

    selected.sort(key=lambda r: (-float(r["total_score"]), str(r["symbol"])))
    return selected


def _choose_basis_and_result(
    res_w: dict[str, Any],
    res_d: dict[str, Any],
    candles_w: list[Any],
    candles_d: list[Any],
) -> tuple[str, dict[str, Any], bool]:
    """Pick timeframe_basis and trend result from only 1w/1d; weekly wins ties unless weekly has no candles."""
    if not candles_w and candles_d:
        return "1d", res_d, False
    if not candles_w and not candles_d:
        return "1d", res_d, True

    cw = _confirmed_leg_count(res_w.get("legs") or [])
    cd = _confirmed_leg_count(res_d.get("legs") or [])

    if cd > cw:
        return "1d", res_d, False
    # Tie or weekly stronger -> weekly (weekly zero-candle case is handled above).
    if candles_w:
        return "1w", res_w, False
    return "1d", res_d, False


def _score_one_symbol(symbol: str, active_deriv: frozenset[str]) -> dict[str, Any]:
    t0 = time.perf_counter()
    active_set = set(active_deriv)
    try:
        candles_w = _fetch_htf_candles(symbol, "1w", active_set)
        res_w = identify_trend(candles_w or [], **SCAN_AND_ANALYSIS_FILTER_DEFAULTS)
        candles_d = _fetch_htf_candles(symbol, "1d", active_set)
        res_d = identify_trend(candles_d or [], **SCAN_AND_ANALYSIS_FILTER_DEFAULTS)

        basis_tf, result, force_zero = _choose_basis_and_result(res_w, res_d, candles_w, candles_d)
        legs = result.get("legs") or []
        confirmed_n = _confirmed_leg_count(legs)

        ipr, ivr, _pc, _vc, _bs, total = compute_ranking_metrics(result)
        retr_bonus = 15.0 if result.get("current_phase") == "retracement" else 0.0
        if force_zero or confirmed_n < 2:
            total = 0.0

        duration = time.perf_counter() - t0
        return {
            "ok": True,
            "symbol": symbol.upper(),
            "timeframe_basis": basis_tf,
            "trend_direction": str(result.get("trend") or "range"),
            "current_phase": result.get("current_phase"),
            "confirmed_leg_count": confirmed_n,
            "leg_structure_json": _serialize_legs(legs),
            "impulse_price_ratio": float(ipr),
            "impulse_velocity_ratio": float(ivr),
            "retracement_phase_bonus": float(retr_bonus),
            "candidate_impulse_bonus": 0.0,
            "total_score": float(total),
            "computation_duration_seconds": duration,
            "error": None,
        }
    except Exception as exc:
        logger.warning("Universe ranking failed for %s: %s", symbol, exc)
        duration = time.perf_counter() - t0
        return {
            "ok": False,
            "symbol": symbol.upper(),
            "timeframe_basis": "1d",
            "trend_direction": "range",
            "current_phase": None,
            "confirmed_leg_count": 0,
            "leg_structure_json": [],
            "impulse_price_ratio": 0.0,
            "impulse_velocity_ratio": 0.0,
            "retracement_phase_bonus": 0.0,
            "candidate_impulse_bonus": 0.0,
            "total_score": 0.0,
            "computation_duration_seconds": duration,
            "error": str(exc)[:2000],
        }


def get_ranking_status() -> dict[str, Any]:
    with _ranking_lock:
        out = dict(_ranking_status)
    out.update(get_analysis_job_flags())
    return out


def trigger_ranking_async(
    force: bool = False,
    universe: str | None = None,
) -> dict[str, Any]:
    with _ranking_lock:
        if _ranking_status.get("in_progress"):
            return {"started": False, "reason": "already_running"}
        _ranking_status["last_error"] = None
        _ranking_status["in_progress"] = True

    thread = threading.Thread(
        target=run_universe_ranking,
        kwargs={"force": force, "universe": universe},
        daemon=True,
    )
    thread.start()
    return {"started": True}


def _run_full_analysis_chain(
    symbols: list[str],
    depth: str = "full_chain",
    force: bool = False,
    max_workers: int = 10,
) -> None:
    """
    Run the full analysis chain for given symbols in order:
    1. Fetch all timeframes
    2. Global structure
    3. Prime impulse (if depth >= global_and_prime)
    4. Walker (if depth >= global_prime_walker)
    5. Candidate impulse (if depth == full_chain)
    6. Market state
    """
    from src.db.session import SessionLocal
    from src.cache.candle_store import refresh_candles
    from src.scanner.global_structure import (
        compute_global_structure_for_symbol,
        compute_prime_impulse_structure,
        compute_walker_for_symbol,
        compute_candidate_impulse_for_symbol,
        compute_and_write_market_state,
    )
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from datetime import datetime, timezone, timedelta

    ALL_TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo"]
    DEPTH_ORDER = [
        "global_only",
        "global_and_prime",
        "global_prime_walker",
        "full_chain",
    ]

    def depth_gte(d: str, threshold: str) -> bool:
        try:
            return DEPTH_ORDER.index(d) >= DEPTH_ORDER.index(threshold)
        except ValueError:
            return False

    def _run(fn, symbol):
        db = SessionLocal()
        try:
            fn(symbol, db)
        except Exception as e:
            logger.warning("%s failed for %s: %s", fn.__name__, symbol, e)
        finally:
            db.close()

    def _fetch_tfs(symbol):
        db = SessionLocal()
        try:
            for tf in ALL_TIMEFRAMES:
                try:
                    refresh_candles(symbol, tf, db)
                except Exception as e:
                    logger.warning("Candle fetch %s %s: %s", symbol, tf, e)
        finally:
            db.close()

    logger.info(
        "Analysis chain: %d symbols depth=%s force=%s",
        len(symbols), depth, force,
    )

    # Step 1 — candles
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_fetch_tfs, sym): sym for sym in symbols}
        for fut in as_completed(futs):
            try:
                fut.result()
            except Exception as e:
                logger.warning("Candle error %s: %s", futs[fut], e)

    # Step 2 — global structure
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {
            ex.submit(_run, compute_global_structure_for_symbol, sym): sym
            for sym in symbols
        }
        for fut in as_completed(futs):
            try:
                fut.result()
            except Exception as e:
                logger.warning("Global structure error %s: %s", futs[fut], e)

    # Step 3 — prime impulse
    if depth_gte(depth, "global_and_prime"):
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {
                ex.submit(_run, compute_prime_impulse_structure, sym): sym
                for sym in symbols
            }
            for fut in as_completed(futs):
                try:
                    fut.result()
                except Exception as e:
                    logger.warning("Prime impulse error %s: %s", futs[fut], e)

    # Step 4 — walker
    if depth_gte(depth, "global_prime_walker"):
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {
                ex.submit(_run, compute_walker_for_symbol, sym): sym
                for sym in symbols
            }
            for fut in as_completed(futs):
                try:
                    fut.result()
                except Exception as e:
                    logger.warning("Walker error %s: %s", futs[fut], e)

    # Step 5 — candidate impulse
    if depth_gte(depth, "full_chain"):
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {
                ex.submit(_run, compute_candidate_impulse_for_symbol, sym): sym
                for sym in symbols
            }
            for fut in as_completed(futs):
                try:
                    fut.result()
                except Exception as e:
                    logger.warning("Candidate error %s: %s", futs[fut], e)

    # Step 6 — market state
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {
            ex.submit(_run, compute_and_write_market_state, sym): sym
            for sym in symbols
        }
        for fut in as_completed(futs):
            try:
                fut.result()
            except Exception as e:
                logger.warning("Market state error %s: %s", futs[fut], e)

    logger.info("Analysis chain complete: %d symbols", len(symbols))


def _run_post_ranking_analysis(symbols: list[str]) -> None:
    """
    After ranking selects top 50:
    1. Fetch all timeframes for all 50 in parallel
    2. Compute global structure for all 50 in parallel
    3. Compute prime impulse for all 50 in parallel
    4. Compute walker for all 50 in parallel
    Each step completes fully before the next begins.
    """
    import logging
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from src.db.session import SessionLocal
    from src.cache.candle_store import refresh_candles
    from src.scanner.global_structure import (
        compute_global_structure_for_symbol,
        compute_prime_impulse_structure,
        compute_walker_for_symbol,
    )

    logger = logging.getLogger(__name__)
    ALL_TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo"]
    MAX_WORKERS = 10

    def _run_with_own_session(fn, symbol):
        db = SessionLocal()
        try:
            fn(symbol, db)
        except Exception as e:
            logger.warning("%s failed for %s: %s", fn.__name__, symbol, e)
        finally:
            db.close()

    def _fetch_all_tfs(symbol):
        db = SessionLocal()
        try:
            for tf in ALL_TIMEFRAMES:
                try:
                    refresh_candles(symbol, tf, db)
                except Exception as e:
                    logger.warning("Candle fetch %s %s: %s", symbol, tf, e)
        finally:
            db.close()

    # Step 1 — fetch all timeframes
    logger.info("Post-ranking Step 1: fetching all timeframes for %d symbols", len(symbols))
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(_fetch_all_tfs, sym): sym for sym in symbols}
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                fut.result()
            except Exception as e:
                logger.warning("Post-ranking candle error %s: %s", sym, e)
    logger.info("Post-ranking Step 1 complete")

    # Step 2 — global structure
    logger.info("Post-ranking Step 2: computing global structure")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {
            ex.submit(_run_with_own_session, compute_global_structure_for_symbol, sym): sym
            for sym in symbols
        }
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                fut.result()
            except Exception as e:
                logger.warning("Post-ranking global structure error %s: %s", sym, e)
    logger.info("Post-ranking Step 2 complete")

    # Step 3 — prime impulse
    logger.info("Post-ranking Step 3: computing prime impulse")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {
            ex.submit(_run_with_own_session, compute_prime_impulse_structure, sym): sym
            for sym in symbols
        }
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                fut.result()
            except Exception as e:
                logger.warning("Post-ranking prime impulse error %s: %s", sym, e)
    logger.info("Post-ranking Step 3 complete")

    # Step 4 — walker
    logger.info("Post-ranking Step 4: computing walker")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {
            ex.submit(_run_with_own_session, compute_walker_for_symbol, sym): sym
            for sym in symbols
        }
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                fut.result()
            except Exception as e:
                logger.warning("Post-ranking walker error %s: %s", sym, e)
    logger.info("Post-ranking Step 4 complete: all %d symbols fully analysed", len(symbols))


def _run_universe_structure_cache_prefill(symbols: list[str]) -> None:
    from src.scanner.global_structure import compute_global_structure_for_symbol

    def _compute_if_missing(sym: str) -> None:
        db = SessionLocal()
        try:
            existing = (
                db.query(GlobalStructureCache)
                .filter(GlobalStructureCache.symbol == sym)
                .first()
            )
            if existing is not None:
                return
            compute_global_structure_for_symbol(sym, db)
            logger.info("Universe structure cache: %s computed", sym)
        except Exception as exc:
            logger.warning("Universe structure cache failed for %s: %s", sym, exc)
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_compute_if_missing, sym) for sym in symbols]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception:
                # Worker-level errors are already logged in _compute_if_missing.
                pass


def run_universe_ranking(
    force: bool = False,
    universe: str | None = None,
) -> None:
    from src.api.routers.setups import (
        MONITORED_CAPACITY,
        _evict_to_capacity,
        _get_effective_scan_settings,
        _get_universe_capacity,
        _get_universe_settings,
    )

    started_wall = datetime.now(timezone.utc)
    job_started = time.perf_counter()
    universe_symbols: list[str] = []
    success_count = 0
    failure_count = 0
    results: list[dict[str, Any]] = []

    with _ranking_lock:
        _ranking_status.update(
            {
                "in_progress": True,
                "total_symbols": 0,
                "symbols_scored": 0,
                "current_symbol": None,
                "started_at": started_wall.isoformat(),
                "completed_at": None,
                "last_error": None,
                "estimated_seconds_remaining": None,
            }
        )

    try:
        db_for_settings = SessionLocal()
        try:
            ranking_settings = _get_effective_scan_settings(db_for_settings)
            try:
                top_n = int(ranking_settings.get("binance_top_n", 350))
            except (TypeError, ValueError):
                top_n = 350
            if top_n not in range(10, 1001):
                top_n = 350
            if universe is not None:
                us_row_top = _get_universe_settings(universe, db_for_settings)
                if us_row_top is not None:
                    try:
                        top_n = int(us_row_top.top_n)
                    except (TypeError, ValueError):
                        pass
                    if top_n not in range(10, 10001):
                        top_n = 350
        finally:
            db_for_settings.close()

        universe_symbols = build_ranking_universe(top_n=top_n)
        if "yfinance" in (ranking_settings.get("brokers") or []):
            from src.api.routers.setups import _yfinance_config_symbols

            universe_symbols = sorted(
                set(universe_symbols) | set(_yfinance_config_symbols())
            )

        if universe is not None:
            universe_symbols = _filter_universe_symbols(universe_symbols, universe)

        try:
            active_deriv = frozenset(get_active_deriv_symbols())
        except Exception:
            active_deriv = frozenset()

        with _ranking_lock:
            _ranking_status["total_symbols"] = len(universe_symbols)

        scored_batch_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_map = {
                executor.submit(_score_one_symbol, sym, active_deriv): sym
                for sym in universe_symbols
            }
            done = 0
            for fut in as_completed(future_map):
                sym = future_map[fut]
                with _ranking_lock:
                    _ranking_status["current_symbol"] = sym
                try:
                    row = fut.result()
                except Exception as exc:
                    row = {
                        "ok": False,
                        "symbol": sym.upper(),
                        "timeframe_basis": "1d",
                        "trend_direction": "range",
                        "current_phase": None,
                        "confirmed_leg_count": 0,
                        "leg_structure_json": [],
                        "impulse_price_ratio": 0.0,
                        "impulse_velocity_ratio": 0.0,
                        "retracement_phase_bonus": 0.0,
                        "candidate_impulse_bonus": 0.0,
                        "total_score": 0.0,
                        "computation_duration_seconds": 0.0,
                        "error": str(exc)[:2000],
                    }
                results.append(row)
                if row.get("ok"):
                    success_count += 1
                else:
                    failure_count += 1
                done += 1
                with _ranking_lock:
                    _ranking_status["symbols_scored"] = done
                    if done % 10 == 0 and done > 0:
                        elapsed = time.perf_counter() - scored_batch_start
                        rate = done / elapsed
                        remaining = len(universe_symbols) - done
                        _ranking_status["estimated_seconds_remaining"] = (
                            int(remaining / rate) if rate > 0 else None
                        )

        now = datetime.now(timezone.utc)
        db = SessionLocal()
        try:
            for row in results:
                sym = row["symbol"]
                existing = db.query(UniverseScore).filter(UniverseScore.symbol == sym).one_or_none()
                payload = {
                    "timeframe_basis": row["timeframe_basis"],
                    "trend_direction": row["trend_direction"],
                    "confirmed_leg_count": row["confirmed_leg_count"],
                    "leg_structure_json": row["leg_structure_json"],
                    "impulse_price_ratio": row["impulse_price_ratio"],
                    "impulse_velocity_ratio": row["impulse_velocity_ratio"],
                    "retracement_phase_bonus": row["retracement_phase_bonus"],
                    "candidate_impulse_bonus": row["candidate_impulse_bonus"],
                    "total_score": row["total_score"],
                    "universe_rank": None,
                    "last_computed_at": now,
                    "computation_duration_seconds": row.get("computation_duration_seconds"),
                }
                if existing is None:
                    db.add(UniverseScore(symbol=sym, **payload))
                else:
                    for k, v in payload.items():
                        setattr(existing, k, v)

            db.commit()

            sorted_rows = sorted(
                results,
                key=lambda r: (-float(r["total_score"]), r["symbol"]),
            )
            rank_map: dict[str, int] = {r["symbol"]: i for i, r in enumerate(sorted_rows, start=1)}

            for row in results:
                u = db.query(UniverseScore).filter(UniverseScore.symbol == row["symbol"]).one_or_none()
                if u is not None:
                    u.universe_rank = rank_map.get(row["symbol"])
            db.commit()

            mins_raw = ranking_settings.get("category_min_slots") or {}
            mins = {
                key: max(0, int(mins_raw.get(key, 0)))
                for key in _CATEGORY_MIN_SLOT_KEYS
            }
            if universe is not None:
                us_row = _get_universe_settings(universe, db)
                if us_row is not None and us_row.category_min_slots_json:
                    for key in _CATEGORY_MIN_SLOT_KEYS:
                        try:
                            v = (us_row.category_min_slots_json or {}).get(key)
                            if v is not None:
                                mins[key] = max(0, int(v))
                        except (TypeError, ValueError):
                            pass
            if universe is not None:
                db_cap = SessionLocal()
                try:
                    capacity = _get_universe_capacity(universe, db_cap)
                finally:
                    db_cap.close()
            else:
                capacity = MONITORED_CAPACITY
            top50 = _select_top_with_category_mins(
                sorted_rows,
                capacity=capacity,
                mins=mins,
            )
            promoted_symbols = {r["symbol"] for r in top50}
            non_promoted_symbols = [
                r["symbol"] for r in sorted_rows if r["symbol"] not in promoted_symbols
            ]
            if universe is not None:
                us_d = _get_universe_settings(universe, db)
                non_top50_depth = (
                    (us_d.non_top_n_depth if us_d is not None else None)
                    or ranking_settings.get(
                        "non_top50_analysis_depth", "global_and_prime"
                    )
                )
            else:
                non_top50_depth = ranking_settings.get(
                    "non_top50_analysis_depth", "global_and_prime"
                )
            if non_top50_depth != "none" and non_promoted_symbols:
                threading.Thread(
                    target=_run_full_analysis_chain,
                    args=(non_promoted_symbols,),
                    kwargs={"depth": non_top50_depth, "force": force},
                    daemon=True,
                ).start()
            for r in top50:
                sym = r["symbol"]
                tf = r["timeframe_basis"]
                trend = r["trend_direction"]
                score = float(r["total_score"])
                current_phase = r.get("current_phase")
                if isinstance(current_phase, str):
                    cp_lower = current_phase.lower()
                else:
                    cp_lower = ""
                status = "MONITORING" if cp_lower == "retracement" else "SCANNING"
                phase_val = current_phase if cp_lower == "retracement" else None

                existing_ms = (
                    db.query(MonitoredSetup)
                    .filter(MonitoredSetup.symbol == sym)
                    .order_by(MonitoredSetup.trend_score.desc(), MonitoredSetup.id.asc())
                    .first()
                )
                univ_val = (
                    universe if universe is not None else _infer_universe(sym)
                )
                if existing_ms is None:
                    db.add(
                        MonitoredSetup(
                            symbol=sym,
                            universe=univ_val,
                            htf_timeframe=tf,
                            htf_trend_direction=trend,
                            current_phase=phase_val,
                            status=status,
                            trend_score=score,
                            structural_state_json={},
                            mtf_alignment={tf: trend},
                            last_checked_at=now,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                else:
                    existing_ms.universe = univ_val
                    existing_ms.htf_timeframe = tf
                    existing_ms.htf_trend_direction = trend
                    existing_ms.trend_score = score
                    existing_ms.current_phase = phase_val
                    existing_ms.status = status
                    existing_ms.updated_at = now
                    existing_ms.last_checked_at = now
                    ma = dict(existing_ms.mtf_alignment or {})
                    ma[tf] = trend
                    existing_ms.mtf_alignment = ma
                db.commit()

            scan_settings = _get_effective_scan_settings(db)
            top_50_symbols = [r["symbol"] for r in top50]
            _prune_non_top_setups(
                db,
                keep_symbols=set(top_50_symbols),
                universe_name=universe,
            )
            _evict_to_capacity(
                db,
                capacity=capacity,
                settings=scan_settings,
                universe=universe,
            )

            # Promotions / evictions have landed; drop the cached
            # /api/setups/universe payload so the next frontend load
            # rebuilds with fresh ranks and scores.
            try:
                from src.api.routers.setups import invalidate_universe_cache

                invalidate_universe_cache()
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Failed to invalidate universe cache: %s", e
                )

            # Analysis cache invalidation: the promoted symbols have just had
            # their structure rewritten (new rank, potentially new global
            # structure/walker). Any cached analysis response for these
            # symbols is stale. Clear per-symbol so the next GET recomputes.
            try:
                from src.api.routers.analysis import (
                    on_structure_updated,
                )

                inv_db = SessionLocal()
                try:
                    for sym in promoted_symbols:
                        on_structure_updated(sym, inv_db)
                finally:
                    inv_db.close()
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Analysis cache invalidation after ranking failed: %s",
                    e,
                )

            duration_sec = time.perf_counter() - job_started
            write_job_log(
                db,
                job_type="universe_ranking",
                started_at=started_wall,
                completed_at=datetime.now(timezone.utc),
                duration_seconds=duration_sec,
                total_symbols=len(universe_symbols),
                success_count=success_count,
                failure_count=failure_count,
                status="completed",
                error_message=None,
                universe_name=universe,
            )

            # The ranking row above is logged as "completed" before the
            # full-chain analysis has even started. Wrap the chain thread
            # so its own success / failure lands in ScanJobLog as a
            # separate row — otherwise a chain crash would be silent.
            analysis_job_start = datetime.now(timezone.utc)
            analysis_symbols = list(top_50_symbols)
            analysis_universe = universe

            def _analysis_chain_wrapper(
                symbols: list[str] = analysis_symbols,
                started_at: datetime = analysis_job_start,
                universe_name: str | None = analysis_universe,
                _force: bool = force,
            ) -> None:
                chain_error: str | None = None
                try:
                    _run_full_analysis_chain(
                        symbols,
                        depth="full_chain",
                        force=_force,
                    )
                except Exception as e:  # noqa: BLE001
                    chain_error = str(e)[:2000]
                    logger.warning(
                        "Post-ranking analysis chain failed for %s: %s",
                        universe_name, e,
                    )
                finally:
                    try:
                        chain_db = SessionLocal()
                        try:
                            now_utc = datetime.now(timezone.utc)
                            write_job_log(
                                chain_db,
                                job_type="universe_analysis_chain",
                                started_at=started_at,
                                completed_at=now_utc,
                                duration_seconds=(
                                    now_utc - started_at
                                ).total_seconds(),
                                total_symbols=len(symbols),
                                success_count=(
                                    0 if chain_error else len(symbols)
                                ),
                                failure_count=0,
                                status=(
                                    "failed" if chain_error else "completed"
                                ),
                                error_message=chain_error,
                                universe_name=universe_name,
                            )
                        finally:
                            chain_db.close()
                    except Exception:
                        pass

            threading.Thread(
                target=_analysis_chain_wrapper,
                daemon=True,
            ).start()
        finally:
            db.close()

        with _ranking_lock:
            _ranking_status["completed_at"] = datetime.now(timezone.utc).isoformat()

    except Exception as exc:
        logger.exception("run_universe_ranking failed: %s", exc)
        duration_sec = time.perf_counter() - job_started
        try:
            db = SessionLocal()
            try:
                write_job_log(
                    db,
                    job_type="universe_ranking",
                    started_at=started_wall,
                    completed_at=datetime.now(timezone.utc),
                    duration_seconds=duration_sec,
                    total_symbols=len(universe_symbols) if universe_symbols else 0,
                    success_count=success_count,
                    failure_count=failure_count,
                    status="failed",
                    error_message=str(exc)[:2000],
                    universe_name=universe,
                )
            finally:
                db.close()
        except Exception:
            pass
        with _ranking_lock:
            _ranking_status["last_error"] = str(exc)
            _ranking_status["completed_at"] = datetime.now(timezone.utc).isoformat()
    finally:
        # Always clear in_progress / current_symbol / ETA, even on a
        # BaseException. Previously these lived in both the success and
        # except branches, so a crash between branches — or a
        # KeyboardInterrupt / SystemExit — could leave in_progress stuck
        # True forever, silently disabling all future ranking jobs.
        with _ranking_lock:
            _ranking_status["in_progress"] = False
            _ranking_status["current_symbol"] = None
            _ranking_status["estimated_seconds_remaining"] = None
