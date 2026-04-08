from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import ExecutionEvent, ExecutionOrder, SystemSettings
from src.execution.contracts import (
    ExecutionEventRecord,
    ExecutionEventType,
    NormalizedOrderIntent,
    OrderStatus,
    OrderSubmissionResponse,
    ProviderId,
)
from src.execution.env_config import execution_enabled, execution_provider
from src.execution.providers.base import ExecutionProvider
from src.execution.providers.deriv import DerivExecutionProvider
from src.execution.providers.stub import StubExecutionProvider
from src.execution.symbol_map import resolve_deriv_symbol

logger = logging.getLogger(__name__)


def _build_provider(provider_id: ProviderId) -> ExecutionProvider:
    if provider_id == ProviderId.STUB:
        return StubExecutionProvider()
    if provider_id == ProviderId.DERIV:
        return DerivExecutionProvider()
    raise ValueError(f"Unsupported provider {provider_id}")


def _resolve_provider_id(intent: NormalizedOrderIntent) -> ProviderId:
    if intent.provider == ProviderId.STUB:
        return ProviderId.STUB
    env_p = execution_provider()
    if env_p == "stub":
        return ProviderId.STUB
    return ProviderId.DERIV


class ExecutionOrchestrator:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _killswitch_active(self) -> bool:
        row = self._db.query(SystemSettings).order_by(SystemSettings.id.asc()).first()
        return bool(row and row.killswitch_active)

    def _persist_event(
        self,
        order_id: int,
        event_type: ExecutionEventType,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        ev = ExecutionEvent(
            order_id=order_id,
            event_type=event_type.value,
            message=message,
            payload_json=payload or {},
            created_at=datetime.now(timezone.utc),
        )
        self._db.add(ev)

    def submit(self, intent: NormalizedOrderIntent) -> OrderSubmissionResponse:
        now = datetime.now(timezone.utc)
        if not execution_enabled():
            return OrderSubmissionResponse(
                ok=False,
                client_order_id=intent.client_order_id,
                status=OrderStatus.REJECTED,
                provider=intent.provider,
                message="Execution disabled (set EXECUTION_ENABLED=1).",
                events=[
                    ExecutionEventRecord(
                        event_type=ExecutionEventType.REJECTED,
                        message="EXECUTION_ENABLED not set",
                    )
                ],
            )

        if self._killswitch_active():
            return OrderSubmissionResponse(
                ok=False,
                client_order_id=intent.client_order_id,
                status=OrderStatus.REJECTED,
                provider=intent.provider,
                message="Killswitch is active.",
                events=[
                    ExecutionEventRecord(
                        event_type=ExecutionEventType.REJECTED,
                        message="killswitch_active",
                    )
                ],
            )

        existing = (
            self._db.query(ExecutionOrder)
            .filter(ExecutionOrder.client_order_id == intent.client_order_id)
            .one_or_none()
        )
        if existing is not None:
            return self._response_from_existing(existing)

        provider_id = _resolve_provider_id(intent)
        provider = _build_provider(provider_id)
        resolved_symbol = resolve_deriv_symbol(intent.symbol) if provider_id == ProviderId.DERIV else intent.symbol.upper()

        order = ExecutionOrder(
            client_order_id=intent.client_order_id,
            provider=provider_id.value,
            symbol=resolved_symbol,
            side=intent.side,
            status=OrderStatus.PENDING.value,
            intent_json=intent.model_dump(mode="json"),
            created_at=now,
            updated_at=now,
        )
        self._db.add(order)
        self._db.flush()

        self._persist_event(
            order.id,
            ExecutionEventType.SUBMITTED,
            message="Order accepted by orchestrator",
            payload={"resolved_symbol": resolved_symbol},
        )

        result = provider.place_order(intent, resolved_symbol)

        if result.success:
            order.status = OrderStatus.FILLED.value
            order.provider_order_id = result.provider_order_id
            order.updated_at = datetime.now(timezone.utc)
            self._persist_event(
                order.id,
                ExecutionEventType.FILLED,
                message="Placement succeeded",
                payload={"diagnostics": result.diagnostics},
            )
            self._db.commit()
            return OrderSubmissionResponse(
                ok=True,
                client_order_id=intent.client_order_id,
                status=OrderStatus.FILLED,
                provider=provider_id,
                provider_order_id=result.provider_order_id,
                message="Filled",
                events=self._events_for_order(order.id),
            )

        order.status = OrderStatus.REJECTED.value
        order.error_message = result.error_message
        order.updated_at = datetime.now(timezone.utc)
        self._persist_event(
            order.id,
            ExecutionEventType.REJECTED,
            message=result.error_message,
            payload={
                "error_code": result.error_code,
                "diagnostics": result.diagnostics,
            },
        )
        self._db.commit()
        return OrderSubmissionResponse(
            ok=False,
            client_order_id=intent.client_order_id,
            status=OrderStatus.REJECTED,
            provider=provider_id,
            message=result.error_message,
            events=self._events_for_order(order.id),
        )

    def _events_for_order(self, order_id: int) -> list[ExecutionEventRecord]:
        rows = (
            self._db.query(ExecutionEvent)
            .filter(ExecutionEvent.order_id == order_id)
            .order_by(ExecutionEvent.id.asc())
            .all()
        )
        out: list[ExecutionEventRecord] = []
        for r in rows:
            try:
                et = ExecutionEventType(r.event_type)
            except ValueError:
                continue
            out.append(
                ExecutionEventRecord(
                    event_type=et,
                    message=r.message,
                    payload=dict(r.payload_json or {}),
                    created_at=r.created_at,
                )
            )
        return out

    def _response_from_existing(self, order: ExecutionOrder) -> OrderSubmissionResponse:
        try:
            st = OrderStatus(order.status)
        except ValueError:
            st = OrderStatus.REJECTED
        return OrderSubmissionResponse(
            ok=st == OrderStatus.FILLED,
            client_order_id=order.client_order_id,
            status=st,
            provider=ProviderId(order.provider),
            provider_order_id=order.provider_order_id,
            message=order.error_message or ("Idempotent replay" if st == OrderStatus.FILLED else None),
            events=self._events_for_order(order.id),
        )

    def list_orders(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = (
            self._db.query(ExecutionOrder)
            .order_by(ExecutionOrder.id.desc())
            .limit(min(limit, 200))
            .all()
        )
        return [
            {
                "id": r.id,
                "client_order_id": r.client_order_id,
                "provider": r.provider,
                "symbol": r.symbol,
                "side": r.side,
                "status": r.status,
                "provider_order_id": r.provider_order_id,
                "error_message": r.error_message,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    def list_events(self, order_id: int) -> list[dict[str, Any]]:
        rows = (
            self._db.query(ExecutionEvent)
            .filter(ExecutionEvent.order_id == order_id)
            .order_by(ExecutionEvent.id.asc())
            .all()
        )
        return [
            {
                "id": r.id,
                "event_type": r.event_type,
                "message": r.message,
                "payload": r.payload_json or {},
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
