from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class ProviderId(str, Enum):
    STUB = "stub"
    DERIV = "deriv"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    WORKING = "working"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ExecutionEventType(str, Enum):
    SUBMITTED = "submitted"
    PROPOSAL_RECEIVED = "proposal_received"
    WORKING = "working"
    FILLED = "filled"
    REJECTED = "rejected"
    ERROR = "error"


class NormalizedOrderIntent(BaseModel):
    """Provider-agnostic intent; Deriv uses proposal+buy fields."""

    client_order_id: str = Field(default_factory=lambda: str(uuid4()))
    provider: ProviderId = ProviderId.DERIV
    symbol: str = Field(..., description="Chronos symbol or Deriv code (e.g. R_10)")
    side: Literal["long", "short"]

    stake_amount: float = Field(..., gt=0, description="Stake for Deriv proposal/buy")
    basis: Literal["stake", "payout"] = "stake"
    currency: str = "USD"
    duration: int = Field(5, ge=1)
    duration_unit: Literal["t", "s", "m", "h", "d"] = "t"

    contract_type: Literal["CALL", "PUT"] | None = Field(
        default=None,
        description="Override; default CALL for long, PUT for short",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("symbol")
    @classmethod
    def strip_symbol(cls, v: str) -> str:
        return v.strip()


class ExecutionEventRecord(BaseModel):
    event_type: ExecutionEventType
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OrderSubmissionResponse(BaseModel):
    ok: bool
    client_order_id: str
    status: OrderStatus
    provider: ProviderId
    provider_order_id: str | None = None
    message: str | None = None
    events: list[ExecutionEventRecord] = Field(default_factory=list)
