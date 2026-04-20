"""API routes for per-universe settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.db.models import UniverseSettings
from src.db.session import get_db

router = APIRouter(
    prefix="/api/universes",
    tags=["universes"],
)


@router.get("")
def list_universes(
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.query(UniverseSettings).all()
    return [
        {
            "universe_name": r.universe_name,
            "capacity": r.capacity,
            "rank_frequency": r.rank_frequency,
            "refresh_offset_hours": r.refresh_offset_hours,
            "refresh_interval_hours": r.refresh_interval_hours,
            "top_n": r.top_n,
            "non_top_n_depth": r.non_top_n_depth,
            "category_min_slots": r.category_min_slots_json,
            "is_active": r.is_active,
        }
        for r in rows
    ]


@router.patch("/{universe_name}")
def update_universe(
    universe_name: str,
    payload: dict,
    db: Session = Depends(get_db),
) -> dict:
    row = (
        db.query(UniverseSettings)
        .filter(UniverseSettings.universe_name == universe_name)
        .first()
    )
    if row is None:
        raise HTTPException(404, "Universe not found")
    allowed = {
        "capacity",
        "rank_frequency",
        "refresh_offset_hours",
        "refresh_interval_hours",
        "top_n",
        "non_top_n_depth",
        "category_min_slots_json",
        "is_active",
    }
    for k, v in payload.items():
        if k in allowed:
            setattr(row, k, v)
    db.commit()
    return {"status": "updated", "universe": universe_name}
