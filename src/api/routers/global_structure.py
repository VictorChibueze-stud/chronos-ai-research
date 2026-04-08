"""API routes for cached reference global structure (daily/weekly)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.db.models import GlobalStructureCache, PrimeImpulseStructure
from src.db.session import get_db
from src.scanner.global_structure import (
    compute_global_structure_for_symbol,
    get_stored_global_structure,
    get_stored_prime_impulse_structure,
)

router = APIRouter(prefix="/api/global-structure", tags=["global-structure"])


def _row_to_json(row: GlobalStructureCache) -> dict[str, Any]:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "reference_timeframe": row.reference_timeframe,
        "confirmed_leg_count": row.confirmed_leg_count,
        "legs_json": row.legs_json,
        "bos_levels_json": row.bos_levels_json,
        "choch_zone_json": row.choch_zone_json,
        "choch_level_json": row.choch_level_json,
        "trend_direction": row.trend_direction,
        "computed_at": row.computed_at.isoformat() if row.computed_at else None,
        "candle_start_timestamp": row.candle_start_timestamp.isoformat()
        if row.candle_start_timestamp
        else None,
        "candle_end_timestamp": row.candle_end_timestamp.isoformat()
        if row.candle_end_timestamp
        else None,
    }


def _prime_row_to_json(row: PrimeImpulseStructure) -> dict[str, Any]:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "source_timeframe": row.source_timeframe,
        "confirmed_leg_count": row.confirmed_leg_count,
        "legs_json": row.legs_json,
        "bos_levels_json": row.bos_levels_json,
        "choch_zone_json": row.choch_zone_json,
        "impulse_start_timestamp": row.impulse_start_timestamp.isoformat()
        if row.impulse_start_timestamp
        else None,
        "impulse_end_timestamp": row.impulse_end_timestamp.isoformat()
        if row.impulse_end_timestamp
        else None,
        "impulse_start_price": row.impulse_start_price,
        "impulse_end_price": row.impulse_end_price,
        "computed_at": row.computed_at.isoformat() if row.computed_at else None,
    }


@router.post("/compute/{symbol}")
def post_compute_global_structure(symbol: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    # Does not take the batch scheduler lock; safe to run while compute_global_structure_all is in progress.
    row = compute_global_structure_for_symbol(symbol, db)
    return _row_to_json(row)


@router.get("/{symbol}/prime-impulse")
def get_prime_impulse_structure(symbol: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = get_stored_prime_impulse_structure(symbol, db)
    if row is None:
        raise HTTPException(status_code=404, detail="No cached prime impulse structure for symbol")
    return _prime_row_to_json(row)


@router.get("/{symbol}")
def get_global_structure(symbol: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = get_stored_global_structure(symbol, db)
    if row is None:
        raise HTTPException(status_code=404, detail="No cached global structure for symbol")
    return _row_to_json(row)
