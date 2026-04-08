from __future__ import annotations

import pytest

from src.execution.contracts import NormalizedOrderIntent, OrderStatus, ProviderId


def test_normalized_order_intent_defaults():
    i = NormalizedOrderIntent(symbol="R_10", side="long", stake_amount=5.0)
    assert i.provider == ProviderId.DERIV
    assert i.basis == "stake"
    assert len(i.client_order_id) > 8


def test_normalized_order_intent_contract_override():
    i = NormalizedOrderIntent(
        symbol="volatility 10 index",
        side="short",
        stake_amount=1.0,
        contract_type="PUT",
    )
    assert i.contract_type == "PUT"


def test_order_status_values():
    assert OrderStatus.FILLED.value == "filled"
