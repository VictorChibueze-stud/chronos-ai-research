"""Manual structure override API.

Allows users to set, update, and reset CHoCH zone overrides for any monitored symbol.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.db.models import ManualStructureOverride
from src.db.session import get_db

router = APIRouter(
    prefix="/api/manual-structure-overrides",
    tags=["manual-structure-overrides"],
)

VALID_OVERRIDE_TYPES = {
    "trend_bounds",
    "global_choch",
    "ichoch",
    "depth_choch",
    "candidate_choch",
    "candidate_ichoch",
}


def _serialize_override(o: ManualStructureOverride) -> dict:
    return {
        "id": o.id,
        "symbol": o.symbol,
        "override_type": o.override_type,
        "lower_boundary": o.lower_boundary,
        "upper_boundary": o.upper_boundary,
        "start_timestamp": o.start_timestamp.isoformat()
        if o.start_timestamp else None,
        "end_timestamp": o.end_timestamp.isoformat()
        if o.end_timestamp else None,
        "trend_start_timestamp": o.trend_start_timestamp.isoformat()
        if o.trend_start_timestamp else None,
        "trend_end_timestamp": o.trend_end_timestamp.isoformat()
        if o.trend_end_timestamp else None,
        "depth_index": o.depth_index,
        "is_active": o.is_active,
        "notes": o.notes,
        "created_at": o.created_at.isoformat(),
        "updated_at": o.updated_at.isoformat(),
        "reset_at": o.reset_at.isoformat()
        if o.reset_at else None,
    }


@router.get("/{symbol}")
def get_overrides(
    symbol: str,
    db: Session = Depends(get_db),
) -> list[dict]:
    """Get all active overrides for a symbol."""
    rows = (
        db.query(ManualStructureOverride)
        .filter(
            ManualStructureOverride.symbol == symbol.strip().upper(),
            ManualStructureOverride.is_active.is_(True),
        )
        .all()
    )
    return [_serialize_override(r) for r in rows]


@router.post("/{symbol}")
def set_override(
    symbol: str,
    payload: dict,
    db: Session = Depends(get_db),
) -> dict:
    """
    Create or update an override for a symbol.
    Body: {
        override_type: str,
        lower_boundary?: float,
        upper_boundary?: float,
        start_timestamp?: str (ISO),
        end_timestamp?: str (ISO),
        trend_start_timestamp?: str (ISO),
        trend_end_timestamp?: str (ISO),
        depth_index?: int,
        notes?: str
    }
    """
    sym = symbol.strip().upper()
    otype = payload.get("override_type", "")
    if otype not in VALID_OVERRIDE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid override_type: {otype}. "
            f"Valid: {sorted(VALID_OVERRIDE_TYPES)}",
        )

    def _parse_ts(val: Any) -> Optional[datetime]:
        if not val:
            return None
        try:
            return datetime.fromisoformat(
                str(val).replace("Z", "+00:00"),
            )
        except Exception:
            return None

    now = datetime.now(timezone.utc)

    existing = (
        db.query(ManualStructureOverride)
        .filter(
            ManualStructureOverride.symbol == sym,
            ManualStructureOverride.override_type == otype,
        )
        .first()
    )

    if existing is None:
        override = ManualStructureOverride(
            symbol=sym,
            override_type=otype,
        )
        db.add(override)
    else:
        override = existing

    override.lower_boundary = payload.get("lower_boundary")
    override.upper_boundary = payload.get("upper_boundary")
    override.start_timestamp = _parse_ts(
        payload.get("start_timestamp"),
    )
    override.end_timestamp = _parse_ts(
        payload.get("end_timestamp"),
    )
    override.trend_start_timestamp = _parse_ts(
        payload.get("trend_start_timestamp"),
    )
    override.trend_end_timestamp = _parse_ts(
        payload.get("trend_end_timestamp"),
    )
    override.depth_index = payload.get("depth_index")
    override.notes = payload.get("notes")
    override.is_active = True
    override.reset_at = None
    override.updated_at = now

    db.commit()
    db.refresh(override)

    return {
        "status": "saved",
        "override": _serialize_override(override),
    }


@router.delete("/{symbol}/{override_type}")
def reset_override(
    symbol: str,
    override_type: str,
    db: Session = Depends(get_db),
) -> dict:
    """
    Reset (deactivate) a specific override type for a symbol.
    Does not delete the row — preserves audit history.
    """
    sym = symbol.strip().upper()
    now = datetime.now(timezone.utc)

    rows = (
        db.query(ManualStructureOverride)
        .filter(
            ManualStructureOverride.symbol == sym,
            ManualStructureOverride.override_type == override_type,
            ManualStructureOverride.is_active.is_(True),
        )
        .all()
    )

    for row in rows:
        row.is_active = False
        row.reset_at = now

    db.commit()

    return {
        "status": "reset",
        "symbol": sym,
        "override_type": override_type,
        "rows_deactivated": len(rows),
    }


@router.delete("/{symbol}")
def reset_all_overrides(
    symbol: str,
    db: Session = Depends(get_db),
) -> dict:
    """Reset all active overrides for a symbol."""
    sym = symbol.strip().upper()
    now = datetime.now(timezone.utc)

    rows = (
        db.query(ManualStructureOverride)
        .filter(
            ManualStructureOverride.symbol == sym,
            ManualStructureOverride.is_active.is_(True),
        )
        .all()
    )

    for row in rows:
        row.is_active = False
        row.reset_at = now

    db.commit()

    return {
        "status": "reset_all",
        "symbol": sym,
        "rows_deactivated": len(rows),
    }
