from __future__ import annotations

from src.execution.contracts import NormalizedOrderIntent, ProviderId
from src.execution.providers.base import ExecutionProvider, ProviderPlacementResult


class StubExecutionProvider:
    """Deterministic fake fills for tests and dry runs."""

    @property
    def provider_id(self) -> ProviderId:
        return ProviderId.STUB

    def place_order(self, intent: NormalizedOrderIntent, resolved_symbol: str) -> ProviderPlacementResult:
        fake_id = f"stub-{intent.client_order_id[:8]}"
        return ProviderPlacementResult(
            success=True,
            provider_order_id=fake_id,
            diagnostics=[
                {"stage": "stub", "symbol": resolved_symbol, "side": intent.side},
            ],
        )
