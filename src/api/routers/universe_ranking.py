"""API routes for universe ranking job."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.db.models import ScanJobLog
from src.db.session import get_db
from src.scanner.universe_ranking import get_ranking_status, trigger_ranking_async

router = APIRouter(prefix="/api/scanner", tags=["scanner"])


@router.post("/rank-universe")
def post_rank_universe() -> dict[str, Any]:
    return trigger_ranking_async()


@router.get("/ranking-status")
def get_ranking_status_endpoint() -> dict[str, Any]:
    return get_ranking_status()


@router.post("/apply-schedule")
def post_apply_schedule(db: Session = Depends(get_db)) -> dict[str, Any]:
    from src.api import main as api_main

    return api_main.apply_scan_schedule_from_db(db)


@router.get("/job-log")
def get_job_log(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = (
        db.query(ScanJobLog)
        .order_by(ScanJobLog.started_at.desc())
        .limit(10)
        .all()
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r.id,
                "job_type": r.job_type,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "duration_seconds": r.duration_seconds,
                "total_symbols": r.total_symbols,
                "success_count": r.success_count,
                "failure_count": r.failure_count,
                "status": r.status,
                "error_message": r.error_message,
            }
        )
    return out
