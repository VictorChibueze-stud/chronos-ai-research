from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from src.execution.contracts import NormalizedOrderIntent, ProviderId


@dataclass
class ProviderPlacementResult:
    success: bool
    provider_order_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    diagnostics: list[dict[str, Any]] = field(default_factory=list)


@runtime_checkable
class ExecutionProvider(Protocol):
    """Routes normalized intents to a broker."""

    @property
    def provider_id(self) -> ProviderId: ...

    def place_order(self, intent: NormalizedOrderIntent, resolved_symbol: str) -> ProviderPlacementResult:
        """Execute placement (e.g. Deriv proposal + buy)."""
        ...
