from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from src.db.models import SymbolAnalysisParams
from src.db.session import SessionLocal, get_db
from src.scanner.global_structure import (
    compute_global_structure_for_symbol,
    compute_prime_impulse_structure,
    compute_walker_for_symbol,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/symbol-params", tags=["symbol-params"])

_ANALYSIS_DEV_DEFAULT_PARAMS: dict[str, Any] = {
    "use_parent_relative_filter": True,
    "min_impulse_parent_ratio": 0.15,
    "use_momentum_filter": True,
    "min_momentum_ratio": 0.5,
    "use_dominance_filter": True,
    "min_dominance_ratio": 1.5,
    "min_swing_candles": None,
    "trend_confirmation_pct": None,
    "max_walk_depth": None,
    "rmt_use_parent_relative_filter": None,
    "rmt_min_impulse_parent_ratio": None,
    "rmt_use_momentum_filter": None,
    "rmt_min_momentum_ratio": None,
    "rmt_use_dominance_filter": None,
    "rmt_min_dominance_ratio": None,
}

_ALLOWED_KEYS = set(_ANALYSIS_DEV_DEFAULT_PARAMS.keys())


def _normalize_symbol(symbol: str) -> str:
    sym = symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=422, detail="symbol is required")
    return sym


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in _ALLOWED_KEYS:
            raise HTTPException(status_code=422, detail=f"unsupported parameter: {key}")
        out[key] = value
    return out


def _recompute_symbol_chain(symbol: str) -> None:
    db = SessionLocal()
    try:
        compute_global_structure_for_symbol(symbol, db)
        compute_prime_impulse_structure(symbol, db)
        compute_walker_for_symbol(symbol, db)
    except Exception:
        logger.exception("symbol params recompute failed symbol=%s", symbol)
    finally:
        db.close()


@router.get("/{symbol}")
def get_symbol_params(symbol: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    sym = _normalize_symbol(symbol)
    row = (
        db.query(SymbolAnalysisParams)
        .filter(SymbolAnalysisParams.symbol == sym)
        .one_or_none()
    )
    if row is None:
        return {
            "symbol": sym,
            "params": dict(_ANALYSIS_DEV_DEFAULT_PARAMS),
            "is_default": True,
        }
    stored = row.params_json if isinstance(row.params_json, dict) else {}
    return {
        "symbol": sym,
        "params": stored,
        "is_default": False,
    }


@router.post("/{symbol}")
def save_symbol_params(
    symbol: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    sym = _normalize_symbol(symbol)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="JSON object body is required")

    cleaned = _sanitize_payload(payload)
    row = (
        db.query(SymbolAnalysisParams)
        .filter(SymbolAnalysisParams.symbol == sym)
        .one_or_none()
    )

    if not cleaned:
        if row is not None:
            db.delete(row)
            db.commit()
    else:
        now = datetime.now(timezone.utc)
        if row is None:
            row = SymbolAnalysisParams(
                symbol=sym,
                params_json=cleaned,
                updated_at=now,
            )
            db.add(row)
        else:
            row.params_json = cleaned
            row.updated_at = now
        db.commit()

    threading.Thread(
        target=_recompute_symbol_chain,
        args=(sym,),
        daemon=True,
    ).start()

    return {
        "symbol": sym,
        "params": cleaned,
        "recomputing": True,
    }
