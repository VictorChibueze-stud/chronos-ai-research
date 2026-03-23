from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from src.db.models import AlertZone, MonitoredSetup


FSM_STATES = {"SCANNING", "MONITORING", "REFINING", "IN_TRADE", "INVALID", "EXPIRED"}


def _deepest_level(structural_state_json: dict[str, Any] | None) -> dict[str, Any] | None:
    levels = (structural_state_json or {}).get("levels") or []
    if not levels:
        return None
    return max(levels, key=lambda level: int(level.get("depth", 0)))


def _derive_ui_state(setup: MonitoredSetup) -> str:
    status = setup.status or "SCANNING"
    if status in {"IN_TRADE", "INVALID", "EXPIRED"}:
        return status

    state = setup.structural_state_json or {}
    if not state.get("walkable", False):
        return "SCANNING"
    if (state.get("total_mitigation_count", 0) > 0) or (state.get("max_depth_reached", 0) > 1):
        return "REFINING"
    if status in FSM_STATES:
        return "MONITORING" if status == "SCANNING" else status
    return "SCANNING"


def _active_zone_bounds(setup: MonitoredSetup) -> tuple[float | None, float | None]:
    active_zone = next(
        (
            zone
            for zone in setup.alert_zones
            if zone.is_active and zone.zone_type in {"DEPTH_CHOCH", "GLOBAL_CHOCH", "MANUAL_OVERRIDE"}
        ),
        None,
    )
    if active_zone is None:
        return None, None
    return active_zone.price_low, active_zone.price_high


def get_all_setups(db: Session) -> pd.DataFrame:
    setups = (
        db.query(MonitoredSetup)
        .order_by(MonitoredSetup.trend_score.desc(), MonitoredSetup.id.asc())
        .all()
    )

    rows: list[dict[str, Any]] = []
    for setup in setups:
        deepest_level = _deepest_level(setup.structural_state_json)
        active_low, active_high = _active_zone_bounds(setup)
        rows.append(
            {
                "setup_id": setup.id,
                "symbol": setup.symbol,
                "timeframe": setup.htf_timeframe,
                "trend": setup.htf_trend_direction,
                "state": _derive_ui_state(setup),
                "trend_score": setup.trend_score,
                "max_depth": (setup.structural_state_json or {}).get("max_depth_reached", 0),
                "deepest_depth": deepest_level.get("depth") if deepest_level else None,
                "mitigations": (setup.structural_state_json or {}).get("total_mitigation_count", 0),
                "waiting_for": (setup.structural_state_json or {}).get("waiting_for", ""),
                "active_zone_low": active_low,
                "active_zone_high": active_high,
                "manual_override": any(zone.is_manual_override for zone in setup.alert_zones),
                "last_checked_at": setup.last_checked_at,
            }
        )

    return pd.DataFrame(rows)


def get_setup_detail(db: Session, setup_id: int) -> MonitoredSetup | None:
    return db.query(MonitoredSetup).filter(MonitoredSetup.id == setup_id).one_or_none()


def drop_setup(db: Session, setup_id: int) -> bool:
    setup = get_setup_detail(db, setup_id)
    if setup is None:
        return False
    db.delete(setup)
    db.commit()
    return True


def add_manual_override(
    db: Session,
    *,
    zone_type: str,
    price_high: float,
    price_low: float,
    symbol: str | None = None,
    setup_id: int | None = None,
    htf_timeframe: str | None = None,
    depth: int | None = None,
    watch_condition: str | None = None,
) -> AlertZone:
    query = db.query(MonitoredSetup)
    if setup_id is not None:
        setup = query.filter(MonitoredSetup.id == setup_id).one_or_none()
    else:
        if symbol is None:
            raise ValueError("Either setup_id or symbol is required")
        query = query.filter(MonitoredSetup.symbol == symbol)
        if htf_timeframe is not None:
            query = query.filter(MonitoredSetup.htf_timeframe == htf_timeframe)
        setup = query.order_by(MonitoredSetup.trend_score.desc(), MonitoredSetup.id.asc()).first()

    if setup is None:
        raise ValueError("Target setup not found")

    resolved_watch_condition = watch_condition
    if resolved_watch_condition is None:
        resolved_watch_condition = "price_crosses_above" if "BOS" in zone_type else "price_enters_zone"

    zone = AlertZone(
        setup_id=setup.id,
        zone_type=zone_type,
        depth=depth,
        price_high=price_high,
        price_low=price_low,
        watch_condition=resolved_watch_condition,
        is_active=True,
        is_manual_override=True,
    )
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return zone