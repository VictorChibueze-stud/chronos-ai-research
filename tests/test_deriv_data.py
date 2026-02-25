import json
from datetime import datetime, timedelta

import os

from src.adapters.deriv_data import DerivConfig, fetch_deriv_ohlc


class FakeWS:
    def __init__(self, responses):
        # responses: list of JSON-serializable objects or strings
        self._responses = [json.dumps(r) if not isinstance(r, str) else r for r in list(responses)]
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)

    def recv(self):
        if not self._responses:
            raise RuntimeError("No more fake responses")
        return self._responses.pop(0)

    def close(self):
        pass


def test_deriv_config_from_env(monkeypatch):
    monkeypatch.setenv("DERIV_APP_ID", "123")
    monkeypatch.setenv("DERIV_API_TOKEN", "tok")
    cfg = DerivConfig.from_env()
    assert cfg.app_id == "123"
    assert cfg.api_token == "tok"


def test_fetch_deriv_ohlc_monkeypatched(monkeypatch):
    # Prepare fake responses: auth ok, then candles
    epoch = int(datetime.utcnow().timestamp())
    fake_candles = [
        {"epoch": epoch, "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1},
        {"epoch": epoch + 60, "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2},
    ]

    responses = [
        {"authorized": True},
        {"candles": fake_candles},
    ]

    def fake_create_conn(url, timeout=30):
        return FakeWS(responses)

    monkeypatch.setattr("websocket.create_connection", fake_create_conn)

    # Provide a dummy config to avoid env dependency in this call
    class DummyCfg:
        app_id = "1"
        api_token = "tok"

    start = datetime.utcfromtimestamp(epoch - 10)
    end = datetime.utcfromtimestamp(epoch + 120)

    candles = fetch_deriv_ohlc("R_10", 60, start, end, cfg=DummyCfg())
    assert len(candles) == 2
    assert candles[0].open == 1.0
    assert candles[1].close == 1.2
    assert candles[0].timestamp < candles[1].timestamp
