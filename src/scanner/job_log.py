"""Append-only persistence for scan / ranking job executions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from src.db.models import ScanJobLog


def write_job_log(
    db: Session,
    job_type: str,
    started_at: datetime,
    completed_at: datetime | None,
    duration_seconds: float | None,
    total_symbols: int,
    success_count: int,
    failure_count: int,
    status: str,
    error_message: str | None,
) -> None:
    """Insert one ScanJobLog row and commit."""
    db.add(
        ScanJobLog(
            job_type=job_type,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
            total_symbols=total_symbols,
            success_count=success_count,
            failure_count=failure_count,
            status=status,
            error_message=error_message,
        )
    )
    db.commit()
