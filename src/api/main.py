from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import analysis, candles, overrides, setups, system
from src.api.routers.setups import ScanRequest, _scan_status, _run_scan_sync
from src.db.session import get_db, init_db
from src.scanner import alert_watcher


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()

    scheduler = AsyncIOScheduler()

    def _run_scheduled_scan() -> None:
        if _scan_status.get("in_progress"):
            return
        import threading

        threading.Thread(target=_run_scan_sync, args=(ScanRequest(),), daemon=True).start()
        job = scheduler.get_job("full_scan_every_4h")
        system.scan_schedule_state["next_scan"] = (
            job.next_run_time.isoformat() if job and job.next_run_time else None
        )

    scheduler.add_job(
        _run_scheduled_scan,
        "interval",
        hours=4,
        id="full_scan_every_4h",
        misfire_grace_time=60,
    )
    scheduler.start()
    asyncio.create_task(alert_watcher.run_alert_watcher())
    job = scheduler.get_job("full_scan_every_4h")
    system.scan_schedule_state["next_scan"] = (
        job.next_run_time.isoformat() if job and job.next_run_time else None
    )

    yield
    scheduler.shutdown(wait=True)


app = FastAPI(title="Ikenga API", lifespan=lifespan)

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
app.include_router(candles.router)


__all__ = ["app", "get_db"]