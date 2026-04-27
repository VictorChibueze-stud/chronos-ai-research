"""Manual structure override API.

Allows users to set, update, and reset CHoCH zone overrides for any monitored symbol.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.db.models import ManualStructureOverride
from src.db.session import get_db
from src.analysis.recompute_orchestrator import trigger_recompute_async

logger = logging.getLogger(__name__)

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

VALID_RECOMPUTE_LAYERS = {"global", "prime", "walker", "candidate"}


def _normalize_recompute_layers(payload: dict | None) -> list[str] | None:
    raw_layers = payload.get("layers") if isinstance(payload, dict) else None
    if raw_layers is None:
        return None
    if not isinstance(raw_layers, list):
        raise HTTPException(status_code=400, detail="layers must be a list of strings")

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_layers:
        layer = str(item or "").strip().lower()
        if not layer:
            continue
        if layer not in VALID_RECOMPUTE_LAYERS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid recompute layer: {layer}. Valid: {sorted(VALID_RECOMPUTE_LAYERS)}",
            )
        if layer in seen:
            continue
        seen.add(layer)
        normalized.append(layer)
    return normalized or None


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
        "expires_at": o.expires_at.isoformat()
        if o.expires_at else None,
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
    override.expires_at = _parse_ts(payload.get("expires_at")) or (now + timedelta(days=30))

    db.commit()
    db.refresh(override)

    layers: list[str] | None
    if otype in {"trend_bounds", "global_choch"}:
        layers = None
    elif otype == "ichoch":
        layers = ["prime", "walker", "candidate"]
    elif otype == "depth_choch":
        layers = ["walker", "candidate"]
    elif otype in {"candidate_choch", "candidate_ichoch"}:
        layers = ["candidate"]
    else:
        layers = None

    trigger_recompute_async(sym, layers=layers)

    return {
        "status": "saved",
        "override": _serialize_override(override),
        "recompute_triggered": True,
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
    trigger_recompute_async(sym, layers=None)

    return {
        "status": "reset",
        "symbol": sym,
        "override_type": override_type,
        "rows_deactivated": len(rows),
        "recompute_triggered": True,
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
    trigger_recompute_async(sym, layers=None)

    return {
        "status": "reset_all",
        "symbol": sym,
        "rows_deactivated": len(rows),
        "recompute_triggered": True,
    }


@router.post("/{symbol}/recompute")
def recompute_overrides(
    symbol: str,
    payload: dict | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Trigger a manual recompute for a symbol using the current active overrides."""
    sym = symbol.strip().upper()
    layers = _normalize_recompute_layers(payload)
    effective_layers = layers or ["global", "prime", "walker", "candidate"]

    trigger_recompute_async(sym, layers=layers)

    return {
        "status": "recompute_triggered",
        "symbol": sym,
        "layers": effective_layers,
        "recompute_triggered": True,
    }
