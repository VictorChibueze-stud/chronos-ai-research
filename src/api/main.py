from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import analysis, candles, execution, global_structure, integrations, overrides, setups, symbol_params, system, trend_visual
from src.api.routers import universe_ranking as universe_ranking_router
from src.adapters.yfinance_data import YFINANCE_SYMBOL_MAP
from src.api.routers.setups import (
    ScanRequest,
    _scan_status,
    _run_scan_sync,
    refresh_universe_cache,
)
from src.cache.candle_store import (
    get_earliest_cached_timestamp,
    lookback_start_time,
    refresh_all_symbols,
    refresh_candles,
)
from src.db.models import MonitoredSetup, UniverseSettings
from src.db.session import SessionLocal, get_db, init_db
from src.scanner import alert_watcher
from src.scanner.analysis_job_state import (
    set_global_structure_running,
    set_prime_impulse_running,
    set_walker_running,
)
from src.scanner.global_structure import (
    compute_global_structure_all,
    compute_prime_impulse_structure_all,
    compute_walker_all,
)
from src.scanner.universe_ranking import get_ranking_status, trigger_ranking_async
from src.fundamentals.scheduler import register_fundamentals_jobs
from src.fundamentals.api.router import router as fundamentals_router
from src.api.routers.manual_overrides import router as manual_structure_overrides_router
from src.api.routers.universes import router as universes_router

logger = logging.getLogger(__name__)

_app_scheduler: AsyncIOScheduler | None = None

UNIVERSE_FREQ_TO_TRIGGER: dict[str, tuple[str, dict[str, Any]]] = {
    "hourly": ("interval", {"hours": 1}),
    "daily": ("cron", {"hour": 1, "minute": 0, "timezone": "UTC"}),
    "weekly": ("cron", {"day_of_week": "sun", "hour": 1, "minute": 0, "timezone": "UTC"}),
    "monthly": ("cron", {"day": 1, "hour": 1, "minute": 0, "timezone": "UTC"}),
}

_UNIVERSE_JOB_KEYS = ("multi_asset", "synthetic", "crypto")

_UNIVERSE_SCHED_FALLBACK: dict[str, dict[str, Any]] = {
    "multi_asset": {
        "rank_frequency": "weekly",
        "refresh_offset_hours": 0,
        "refresh_interval_hours": 4,
    },
    "synthetic": {
        "rank_frequency": "daily",
        "refresh_offset_hours": 1,
        "refresh_interval_hours": 4,
    },
    "crypto": {
        "rank_frequency": "daily",
        "refresh_offset_hours": 2,
        "refresh_interval_hours": 4,
    },
}


def _utc_next_interval_start(offset_hours: int) -> datetime:
    now = datetime.now(timezone.utc)
    h = int(offset_hours) % 24
    cand = now.replace(hour=h, minute=0, second=0, microsecond=0)
    if cand <= now:
        cand = cand + timedelta(days=1)
    return cand


def _us_sched_values(
    universe_name: str,
    us: UniverseSettings | None,
) -> dict[str, Any]:
    fb = _UNIVERSE_SCHED_FALLBACK[universe_name]
    if us is None:
        return {**fb, "is_active": True}
    return {
        "rank_frequency": us.rank_frequency or fb["rank_frequency"],
        "refresh_offset_hours": int(
            us.refresh_offset_hours
            if us.refresh_offset_hours is not None
            else fb["refresh_offset_hours"]
        ),
        "refresh_interval_hours": int(
            us.refresh_interval_hours
            if us.refresh_interval_hours is not None
            else fb["refresh_interval_hours"]
        ),
        "is_active": bool(us.is_active),
    }


def _make_ranking_fn(univ: str):
    def _fn() -> None:
        if get_ranking_status().get("in_progress"):
            logger.info(
                "Scheduled universe ranking skipped (%s): already in progress",
                univ,
            )
            return
        out = trigger_ranking_async(force=False, universe=univ)
        if not out.get("started"):
            logger.info(
                "Scheduled universe ranking skipped (%s): %s",
                univ,
                out.get("reason", "unknown"),
            )
        else:
            logger.info("Scheduled universe ranking started (%s)", univ)

    _fn.__name__ = f"_rank_{univ}"
    return _fn


def _make_refresh_fn(univ: str):
    def _fn() -> None:
        if _scan_status.get("in_progress"):
            return
        threading.Thread(
            target=_run_scan_sync,
            args=(ScanRequest(),),
            kwargs={"universe_filter": univ},
            daemon=True,
        ).start()
        sch = _app_scheduler
        if sch is None:
            return
        job = sch.get_job(f"refresh_{univ}")
        system.scan_schedule_state["next_scan"] = (
            job.next_run_time.isoformat() if job and job.next_run_time else None
        )

    _fn.__name__ = f"_refresh_{univ}"
    return _fn


def _schedule_per_universe_jobs(sched: AsyncIOScheduler, db: Session) -> None:
    rows = {r.universe_name: r for r in db.query(UniverseSettings).all()}
    for universe_name in _UNIVERSE_JOB_KEYS:
        rank_jid = f"rank_{universe_name}"
        refresh_jid = f"refresh_{universe_name}"
        for jid in (rank_jid, refresh_jid):
            try:
                sched.remove_job(jid)
            except JobLookupError:
                pass
        us = rows.get(universe_name)
        if us is not None and not us.is_active:
            continue
        vals = _us_sched_values(universe_name, us)
        if not vals.get("is_active", True):
            continue
        freq = str(vals["rank_frequency"])
        trigger, kw = UNIVERSE_FREQ_TO_TRIGGER.get(freq, UNIVERSE_FREQ_TO_TRIGGER["daily"])
        sched.add_job(
            _make_ranking_fn(universe_name),
            trigger,
            id=rank_jid,
            misfire_grace_time=300,
            **kw,
        )
        off = int(vals["refresh_offset_hours"])
        hrs = int(vals["refresh_interval_hours"])
        if hrs < 1:
            hrs = 4
        start_date = _utc_next_interval_start(off)
        sched.add_job(
            _make_refresh_fn(universe_name),
            "interval",
            hours=hrs,
            start_date=start_date,
            id=refresh_jid,
            misfire_grace_time=60,
        )

_global_structure_job_lock = threading.Lock()
_prime_impulse_job_lock = threading.Lock()
_walker_all_job_lock = threading.Lock()

PRELOAD_TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo"]


def _global_structure_all_job_entry(source: str) -> None:
    """Runs compute_global_structure_all; skip if another batch job holds the lock."""
    if not _global_structure_job_lock.acquire(blocking=False):
        logger.info("global_structure_all_job skipped (%s): already running", source)
        return
    set_global_structure_running(True)
    logger.info("global structure job starting (%s)", source)
    success = False
    try:
        db = SessionLocal()
        try:
            summary = compute_global_structure_all(db)
            logger.info("global_structure job finished (%s): %s", source, summary)
            success = True
        finally:
            db.close()
    except Exception:
        logger.exception("global_structure job failed (%s)", source)
    finally:
        set_global_structure_running(False)
        _global_structure_job_lock.release()
    if success and source == "after_preload":
        _spawn_prime_impulse_all_job("after_global_startup")


def _spawn_global_structure_all_job(source: str) -> None:
    threading.Thread(target=_global_structure_all_job_entry, args=(source,), daemon=True).start()


def _prime_impulse_all_job_entry(source: str) -> None:
    if not _prime_impulse_job_lock.acquire(blocking=False):
        logger.info("prime_impulse skipped (%s): already running", source)
        return
    set_prime_impulse_running(True)
    logger.info("prime impulse job starting (%s)", source)
    success = False
    try:
        db = SessionLocal()
        try:
            summary = compute_prime_impulse_structure_all(db)
            logger.info("prime_impulse job finished (%s): %s", source, summary)
            success = True
        finally:
            db.close()
    except Exception:
        logger.exception("prime_impulse job failed (%s)", source)
    finally:
        set_prime_impulse_running(False)
        _prime_impulse_job_lock.release()
    if success:
        _spawn_walker_all_job(f"after_prime_{source}")


def _spawn_prime_impulse_all_job(source: str) -> None:
    threading.Thread(target=_prime_impulse_all_job_entry, args=(source,), daemon=True).start()


def _walker_all_job_entry(source: str) -> None:
    if not _walker_all_job_lock.acquire(blocking=False):
        logger.info("walker batch skipped (%s): already running", source)
        return
    set_walker_running(True)
    logger.info("walker job starting (%s)", source)
    try:
        db = SessionLocal()
        try:
            summary = compute_walker_all(db)
            logger.info("walker job finished (%s): %s", source, summary)
        finally:
            db.close()
    except Exception:
        logger.exception("walker job failed (%s)", source)
    finally:
        set_walker_running(False)
        _walker_all_job_lock.release()


def _spawn_walker_all_job(source: str) -> None:
    threading.Thread(target=_walker_all_job_entry, args=(source,), daemon=True).start()


def _recovery_pass_global_structure() -> None:
    import time

    from src.db.models import GlobalStructureCache, MonitoredSetup
    from src.scanner.global_structure import compute_global_structure_for_symbol

    logger.info("Recovery pass: waiting 60s for global structure job")
    time.sleep(60)

    db = SessionLocal()
    try:
        monitored = [r[0] for r in db.query(MonitoredSetup.symbol).distinct().all()]
        cached = {r[0] for r in db.query(GlobalStructureCache.symbol).all()}
        missing = [s for s in monitored if s not in cached]

        if missing:
            logger.info("Recovery pass: %d symbols missing, retrying", len(missing))
            for sym in missing:
                try:
                    compute_global_structure_for_symbol(sym, db)
                    logger.info("Recovery pass: computed global structure for %s", sym)
                except Exception as e:
                    logger.warning("Recovery pass: failed for %s: %s", sym, e)
        else:
            logger.info("Recovery pass: all monitored symbols cached")
    finally:
        db.close()


def _preload_monitored_setups_cache() -> None:
    """One-shot: for each monitored symbol, ensure cache covers timeframe_windows lookback from oldest bar.

    Skips a pair when the earliest cached candle is at or before the required lookback start.
    Empty or shallow cache triggers fetch; shallow uses a full lookback refresh (not incremental).
    """
    try:
        db = SessionLocal()
    except Exception as e:
        logger.warning("Monitored-setups preload: could not open DB session: %s", e)
        return
    try:
        logger.info("Monitored-setups preload starting")
        symbols = sorted(
            {str(r[0]).upper() for r in db.query(MonitoredSetup.symbol).distinct().all() if r[0]}
        )
        if not symbols:
            logger.info("Monitored-setups preload: no symbols in monitored_setups")
            return
        logger.info(
            "Monitored-setups preload: %d symbols × %d timeframes",
            len(symbols),
            len(PRELOAD_TIMEFRAMES),
        )
        for sym in symbols:
            for tf in PRELOAD_TIMEFRAMES:
                try:
                    need_start = lookback_start_time(tf)
                    oldest = get_earliest_cached_timestamp(sym, tf, db)
                    if oldest is not None and oldest <= need_start:
                        continue
                    n = refresh_candles(sym, tf, db, force_full=(oldest is not None))
                    logger.info("Monitored-setups preload: %s %s — %s candles written", sym, tf, n)
                except Exception as pair_exc:
                    logger.warning(
                        "Monitored-setups preload failed %s %s: %s",
                        sym,
                        tf,
                        pair_exc,
                    )
        logger.info("Monitored-setups preload complete")
        _spawn_global_structure_all_job("after_preload")
        threading.Thread(target=_recovery_pass_global_structure, daemon=True).start()
    except Exception as e:
        logger.warning("Monitored-setups preload failed: %s", e)
    finally:
        db.close()


def _warm_cache() -> None:
    db = SessionLocal()
    try:
        monitored = [
            r[0] for r in db.query(MonitoredSetup.symbol).distinct().all()
        ]
        all_syms = list(set(monitored) | set(YFINANCE_SYMBOL_MAP.keys()))
        timeframes = ["5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo"]
        logger.info("Cache warm: %d symbols × %d timeframes", len(all_syms), len(timeframes))
        refresh_all_symbols(all_syms, timeframes, db, recent_only=True, recent_count=500)
    except Exception as e:
        logger.warning("Cache warm failed: %s", e)
    finally:
        db.close()


def _job_schedule_detail(sched: AsyncIOScheduler, job_id: str) -> dict[str, Any]:
    job = sched.get_job(job_id)
    if job is None:
        return {"job_id": job_id, "trigger": None, "next_run_time": None}
    nxt = job.next_run_time.isoformat() if job.next_run_time else None
    return {"job_id": job_id, "trigger": str(job.trigger), "next_run_time": nxt}


def _reschedule_universe_ranking_job(
    sched: AsyncIOScheduler,
    universe: str,
    freq: str,
) -> None:
    trigger, kw = UNIVERSE_FREQ_TO_TRIGGER.get(freq, UNIVERSE_FREQ_TO_TRIGGER["daily"])
    jid = f"rank_{universe}"
    try:
        sched.reschedule_job(jid, trigger=trigger, misfire_grace_time=300, **kw)
    except Exception as e:
        logger.warning("reschedule_job %s failed (%s), using remove+add", jid, e)
        try:
            sched.remove_job(jid)
        except JobLookupError:
            pass
        sched.add_job(
            _make_ranking_fn(universe),
            trigger,
            id=jid,
            misfire_grace_time=300,
            **kw,
        )


def _reschedule_active_refresh_job(
    sched: AsyncIOScheduler,
    universe: str,
    hours: int,
    offset_hours: int,
) -> None:
    jid = f"refresh_{universe}"
    start_date = _utc_next_interval_start(offset_hours)
    try:
        sched.reschedule_job(
            jid,
            trigger="interval",
            hours=hours,
            start_date=start_date,
            misfire_grace_time=60,
        )
    except Exception as e:
        logger.warning("reschedule_job %s failed (%s), using remove+add", jid, e)
        try:
            sched.remove_job(jid)
        except JobLookupError:
            pass
        sched.add_job(
            _make_refresh_fn(universe),
            "interval",
            hours=hours,
            start_date=start_date,
            id=jid,
            misfire_grace_time=60,
        )


def apply_scan_schedule_from_db(db: Session) -> dict[str, Any]:
    """Reschedule per-universe rank and refresh jobs from universe_settings rows."""
    sch = _app_scheduler
    if sch is None or not sch.running:
        return {
            "ok": False,
            "reason": "scheduler not running",
            "jobs": [],
        }
    try:
        _schedule_per_universe_jobs(sch, db)
        jobs: list[dict[str, Any]] = []
        for name in _UNIVERSE_JOB_KEYS:
            jobs.append(_job_schedule_detail(sch, f"rank_{name}"))
            jobs.append(_job_schedule_detail(sch, f"refresh_{name}"))
        job = sch.get_job("refresh_multi_asset")
        system.scan_schedule_state["next_scan"] = (
            job.next_run_time.isoformat() if job and job.next_run_time else None
        )
    except Exception:
        logger.exception("apply_scan_schedule_from_db failed")
        return {
            "ok": False,
            "reason": "reschedule failed",
            "jobs": [],
        }

    return {
        "ok": True,
        "jobs": jobs,
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _app_scheduler

    init_db()

    threading.Thread(target=_warm_cache, daemon=True).start()
    threading.Thread(target=refresh_universe_cache, daemon=True).start()

    scheduler = AsyncIOScheduler()
    _app_scheduler = scheduler

    db_sched = SessionLocal()
    try:
        _schedule_per_universe_jobs(scheduler, db_sched)
    finally:
        db_sched.close()

    scheduler.add_job(
        lambda: threading.Thread(target=refresh_universe_cache, daemon=True).start(),
        "interval",
        minutes=5,
        id="universe_cache_refresh_5m",
        misfire_grace_time=60,
    )
    scheduler.add_job(
        lambda: threading.Thread(target=_warm_cache, daemon=True).start(),
        "interval",
        minutes=15,
        id="candle_cache_refresh_15m",
        misfire_grace_time=60,
    )
    register_fundamentals_jobs(scheduler)
    scheduler.start()
    asyncio.create_task(alert_watcher.run_alert_watcher())
    job = scheduler.get_job("refresh_multi_asset")
    system.scan_schedule_state["next_scan"] = (
        job.next_run_time.isoformat() if job and job.next_run_time else None
    )

    try:
        db_apply = SessionLocal()
        try:
            apply_scan_schedule_from_db(db_apply)
        finally:
            db_apply.close()
    except Exception:
        logger.exception("Startup apply_scan_schedule_from_db failed")

    threading.Thread(target=_preload_monitored_setups_cache, daemon=True).start()

    yield
    _app_scheduler = None
    scheduler.shutdown(wait=True)


app = FastAPI(title="Ikenga API", lifespan=lifespan)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "Ikenga API",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": "/api/system/health",
    }


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(setups.router)
app.include_router(analysis.router)
app.include_router(analysis.universe_router)
app.include_router(overrides.router)
app.include_router(manual_structure_overrides_router)
app.include_router(candles.router)
app.include_router(trend_visual.router)
app.include_router(integrations.router)
app.include_router(execution.router)
app.include_router(global_structure.router)
app.include_router(universe_ranking_router.router)
app.include_router(universes_router)
app.include_router(symbol_params.router)
app.include_router(fundamentals_router)


__all__ = ["app", "get_db", "apply_scan_schedule_from_db"]