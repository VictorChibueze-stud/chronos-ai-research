from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from src.execution.contracts import NormalizedOrderIntent, ProviderId
from src.execution.providers.deriv import DerivExecutionProvider


def test_deriv_provider_happy_path():
    intent = NormalizedOrderIntent(
        symbol="R_10",
        side="long",
        stake_amount=10.0,
        provider=ProviderId.DERIV,
    )

    responses = [
        json.dumps({"authorize": {"loginid": "VR123"}}),
        json.dumps({"proposal": {"id": "prop-1", "ask_price": 10.0}}),
        json.dumps({"buy": {"contract_id": "c-99"}}),
    ]

    mock_ws = MagicMock()

    def fake_recv():
        if responses:
            return responses.pop(0)
        return json.dumps({})

    mock_ws.recv.side_effect = fake_recv
    mock_ws.send = MagicMock()

    with patch("src.execution.providers.deriv.websocket.create_connection", return_value=mock_ws):
        p = DerivExecutionProvider(app_id="1", api_token="tok")
        r = p.place_order(intent, "R_10")

    assert r.success is True
    assert r.provider_order_id == "c-99"
