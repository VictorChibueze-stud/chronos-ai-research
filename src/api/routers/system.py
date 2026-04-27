from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.db.models import MonitoredSetup, SystemSettings
from src.db.session import get_db


router = APIRouter(prefix="/api/system", tags=["system"])

# Updated by the background scheduler in src/api/main.py.
scan_schedule_state: dict[str, str | None] = {
    "last_scan": None,
    "next_scan": None,
}


def _get_or_create_settings(db: Session) -> SystemSettings:
    settings = db.query(SystemSettings).order_by(SystemSettings.id.asc()).first()
    if settings is None:
        settings = SystemSettings(killswitch_active=False)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@router.get("/health")
def get_health(db: Session = Depends(get_db)) -> dict[str, Any]:
    from src.api.routers.setups import _scan_status, _universe_endpoint_cache
    from src.db.models import UniverseSettings

    universe_rows = (
        db.query(UniverseSettings)
        .filter(UniverseSettings.is_active == True)  # noqa: E712
        .all()
    )
    total_capacity = sum(u.capacity for u in universe_rows)
    if total_capacity == 0:
        total_capacity = 50  # fallback when universe_settings is empty

    cache_built_at = _universe_endpoint_cache.get("built_at")
    universe_cache_age_seconds: int | None = None
    if cache_built_at is not None:
        universe_cache_age_seconds = int(
            (datetime.now(timezone.utc) - cache_built_at).total_seconds()
        )

    try:
        from src.fundamentals.llm.router import get_quota_status

        llm_quota: dict[str, int] = get_quota_status()
    except Exception:
        llm_quota = {}

    return {
        "status": "online",
        "active_setups": db.query(MonitoredSetup).count(),
        "max_capacity": total_capacity,
        "last_scan": scan_schedule_state["last_scan"],
        "next_scan": scan_schedule_state["next_scan"],
        "scan_in_progress": bool(_scan_status.get("in_progress", False)),
        "universe_cache_age_seconds": universe_cache_age_seconds,
        "llm_quota_remaining": llm_quota,
    }


@router.get("/killswitch")
def get_killswitch(db: Session = Depends(get_db)) -> dict[str, bool]:
    settings = _get_or_create_settings(db)
    return {"killswitch_active": settings.killswitch_active}


@router.post("/killswitch")
def toggle_killswitch(db: Session = Depends(get_db)) -> dict[str, bool]:
    settings = _get_or_create_settings(db)
    settings.killswitch_active = not settings.killswitch_active
    db.commit()
    db.refresh(settings)
    return {"killswitch_active": settings.killswitch_active}


@router.get("/scan-status")
def get_scan_status() -> dict[str, object]:
    from src.api.routers.setups import _scan_status

    return dict(_scan_status)