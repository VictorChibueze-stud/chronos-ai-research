from __future__ import annotations

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
def get_health(db: Session = Depends(get_db)) -> dict[str, int | str | bool | None]:
    from src.api.routers.setups import _scan_status
    from src.db.models import UniverseSettings

    universe_rows = (
        db.query(UniverseSettings)
        .filter(UniverseSettings.is_active == True)  # noqa: E712
        .all()
    )
    total_capacity = sum(u.capacity for u in universe_rows)
    if total_capacity == 0:
        total_capacity = 50  # fallback when universe_settings is empty

    return {
        "status": "online",
        "active_setups": db.query(MonitoredSetup).count(),
        "max_capacity": total_capacity,
        "last_scan": scan_schedule_state["last_scan"],
        "next_scan": scan_schedule_state["next_scan"],
        "scan_in_progress": bool(_scan_status.get("in_progress", False)),
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