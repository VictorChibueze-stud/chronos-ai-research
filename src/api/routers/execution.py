from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.cache import candle_store
from src.db.models import ExecutionOrder
from src.db.session import get_db
from src.execution.contracts import NormalizedOrderIntent, OrderSubmissionResponse
from src.execution.env_config import execution_enabled, execution_paper_only, execution_provider
from src.execution.orchestrator import ExecutionOrchestrator
from src.execution.signal_bridge import signal_to_intent, trend_snapshot_to_signal

router = APIRouter(prefix="/api/execution", tags=["execution"])


class FromSignalRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    timeframe: str = Field("1h", min_length=1)
    stake_amount: float = Field(10.0, gt=0)


@router.get("/status")
def get_execution_status() -> dict[str, bool | str]:
    return {
        "execution_enabled": execution_enabled(),
        "execution_paper_only": execution_paper_only(),
        "execution_provider": execution_provider(),
    }


@router.post("/orders", response_model=OrderSubmissionResponse)
def post_execution_order(
    body: NormalizedOrderIntent,
    db: Session = Depends(get_db),
) -> OrderSubmissionResponse:
    orch = ExecutionOrchestrator(db)
    return orch.submit(body)


@router.post("/from-signal", response_model=OrderSubmissionResponse)
def post_execution_from_signal(
    body: FromSignalRequest,
    db: Session = Depends(get_db),
) -> OrderSubmissionResponse:
    try:
        candles = candle_store.get_candles(body.symbol.upper(), body.timeframe.lower(), db)
    except candle_store.CandleDataError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"reason": exc.reason, "message": str(exc)},
        ) from exc
    if not candles:
        raise HTTPException(status_code=422, detail="No candles for symbol/timeframe")
    signal = trend_snapshot_to_signal(candles)
    intent = signal_to_intent(signal, symbol=body.symbol, stake_amount=body.stake_amount)
    if intent is None:
        raise HTTPException(
            status_code=422,
            detail={"message": "No actionable signal (need impulse phase with directional trend).", "signal": signal.status},
        )
    orch = ExecutionOrchestrator(db)
    return orch.submit(intent)


@router.get("/orders")
def list_execution_orders(
    limit: int = 50,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return {"items": ExecutionOrchestrator(db).list_orders(limit=limit)}


@router.get("/orders/{order_id}/events")
def list_order_events(
    order_id: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    order = db.query(ExecutionOrder).filter(ExecutionOrder.id == order_id).one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    rows = ExecutionOrchestrator(db).list_events(order_id)
    return {"order_id": order_id, "items": rows}
