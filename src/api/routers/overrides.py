from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.db.models import AlertZone, MonitoredSetup
from src.db.session import get_db


router = APIRouter(prefix="/api/overrides", tags=["overrides"])


class OverrideRequest(BaseModel):
    symbol: str
    zone_type: str
    price_high: float
    price_low: float


def _serialize_zone(zone: AlertZone, symbol: str) -> dict[str, Any]:
    return {
        "id": zone.id,
        "setup_id": zone.setup_id,
        "symbol": symbol,
        "zone_type": zone.zone_type,
        "depth": zone.depth,
        "price_high": zone.price_high,
        "price_low": zone.price_low,
        "is_active": zone.is_active,
        "watch_condition": zone.watch_condition,
        "is_manual_override": zone.is_manual_override,
    }


@router.post("")
def create_override(request: OverrideRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    setup = (
        db.query(MonitoredSetup)
        .filter(MonitoredSetup.symbol == request.symbol)
        .order_by(MonitoredSetup.trend_score.desc(), MonitoredSetup.id.asc())
        .first()
    )
    if setup is None:
        raise HTTPException(status_code=404, detail="Setup not found")

    zone = AlertZone(
        setup_id=setup.id,
        zone_type=request.zone_type,
        depth=None,
        price_high=request.price_high,
        price_low=request.price_low,
        is_active=True,
        watch_condition="price_enters_zone",
        is_manual_override=True,
    )
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return _serialize_zone(zone, setup.symbol)


@router.get("")
def list_overrides(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    zones = (
        db.query(AlertZone)
        .join(AlertZone.setup)
        .filter(AlertZone.is_manual_override.is_(True))
        .order_by(AlertZone.id.asc())
        .all()
    )
    return [_serialize_zone(zone, zone.setup.symbol) for zone in zones]


@router.delete("/{zone_id}")
def delete_override(zone_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    zone = (
        db.query(AlertZone)
        .filter(AlertZone.id == zone_id, AlertZone.is_manual_override.is_(True))
        .one_or_none()
    )
    if zone is None:
        raise HTTPException(status_code=404, detail="Override not found")

    db.delete(zone)
    db.commit()
    return {"deleted": True, "zone_id": zone_id}