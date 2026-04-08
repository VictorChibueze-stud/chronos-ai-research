"""Full-universe HTF ranking job: weekly/daily trend, score, persist, promote top 50."""

from __future__ import annotations

import logging
import math
import threading
import time
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
from src.db.models import MonitoredSetup, UniverseScore
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


def compute_ranking_metrics(result: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
    """Impulse ratios, components, base_score, total_score (before min-legs zeroing)."""
    legs = [l for l in (result.get("legs") or []) if l.get("confirmed") is True]
    impulses = [l for l in legs if l.get("type") == "impulse" and l.get("end_price") is not None]
    retracements = [l for l in legs if l.get("type") == "retracement" and l.get("end_price") is not None]

    confirmed_count = len(legs)
    if confirmed_count < 3:
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


def _choose_basis_and_result(
    res_w: dict[str, Any],
    res_d: dict[str, Any],
) -> tuple[str, dict[str, Any], bool]:
    """Pick timeframe_basis and trend result; force_score_zero if neither has >=2 confirmed legs."""
    cw = _confirmed_leg_count(res_w.get("legs") or [])
    cd = _confirmed_leg_count(res_d.get("legs") or [])

    if cw >= 2 and cd >= 2:
        if cd > cw:
            return "1d", res_d, False
        return "1w", res_w, False
    if cw >= 2:
        return "1w", res_w, False
    if cd >= 2:
        return "1d", res_d, False
    return "1d", res_d, True


def _score_one_symbol(symbol: str, active_deriv: frozenset[str]) -> dict[str, Any]:
    t0 = time.perf_counter()
    active_set = set(active_deriv)
    try:
        candles_w = _fetch_htf_candles(symbol, "1w", active_set)
        res_w = identify_trend(candles_w or [], **SCAN_AND_ANALYSIS_FILTER_DEFAULTS)
        candles_d = _fetch_htf_candles(symbol, "1d", active_set)
        res_d = identify_trend(candles_d or [], **SCAN_AND_ANALYSIS_FILTER_DEFAULTS)

        basis_tf, result, force_zero = _choose_basis_and_result(res_w, res_d)
        legs = result.get("legs") or []
        confirmed_n = _confirmed_leg_count(legs)

        ipr, ivr, _pc, _vc, _bs, total = compute_ranking_metrics(result)
        retr_bonus = 15.0 if result.get("current_phase") == "retracement" else 0.0
        if force_zero or confirmed_n < 3:
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


def trigger_ranking_async() -> dict[str, Any]:
    with _ranking_lock:
        if _ranking_status.get("in_progress"):
            return {"started": False, "reason": "already_running"}
        _ranking_status["last_error"] = None
        _ranking_status["in_progress"] = True

    thread = threading.Thread(target=run_universe_ranking, daemon=True)
    thread.start()
    return {"started": True}


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


def run_universe_ranking() -> None:
    from src.api.routers.setups import (
        MONITORED_CAPACITY,
        _evict_to_capacity,
        _get_effective_scan_settings,
    )

    started_wall = datetime.now(timezone.utc)
    job_started = time.perf_counter()
    universe: list[str] = []
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
        finally:
            db_for_settings.close()

        universe = build_ranking_universe(top_n=top_n)
        if "yfinance" in (ranking_settings.get("brokers") or []):
            from src.api.routers.setups import _yfinance_config_symbols

            universe = sorted(set(universe) | set(_yfinance_config_symbols()))

        try:
            active_deriv = frozenset(get_active_deriv_symbols())
        except Exception:
            active_deriv = frozenset()

        with _ranking_lock:
            _ranking_status["total_symbols"] = len(universe)

        scored_batch_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_map = {executor.submit(_score_one_symbol, sym, active_deriv): sym for sym in universe}
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
                        remaining = len(universe) - done
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

            top50 = sorted_rows[:50]
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
                if existing_ms is None:
                    db.add(
                        MonitoredSetup(
                            symbol=sym,
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
            _evict_to_capacity(db, capacity=MONITORED_CAPACITY, settings=scan_settings)

            top_50_symbols = [r["symbol"] for r in sorted_rows[:50]]

            duration_sec = time.perf_counter() - job_started
            write_job_log(
                db,
                job_type="universe_ranking",
                started_at=started_wall,
                completed_at=datetime.now(timezone.utc),
                duration_seconds=duration_sec,
                total_symbols=len(universe),
                success_count=success_count,
                failure_count=failure_count,
                status="completed",
                error_message=None,
            )
            threading.Thread(
                target=_run_post_ranking_analysis,
                args=(top_50_symbols,),
                daemon=True,
            ).start()
        finally:
            db.close()

        with _ranking_lock:
            _ranking_status["in_progress"] = False
            _ranking_status["completed_at"] = datetime.now(timezone.utc).isoformat()
            _ranking_status["current_symbol"] = None
            _ranking_status["estimated_seconds_remaining"] = None

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
                    total_symbols=len(universe) if universe else 0,
                    success_count=success_count,
                    failure_count=failure_count,
                    status="failed",
                    error_message=str(exc)[:2000],
                )
            finally:
                db.close()
        except Exception:
            pass
        with _ranking_lock:
            _ranking_status["in_progress"] = False
            _ranking_status["last_error"] = str(exc)
            _ranking_status["completed_at"] = datetime.now(timezone.utc).isoformat()
            _ranking_status["current_symbol"] = None
            _ranking_status["estimated_seconds_remaining"] = None
