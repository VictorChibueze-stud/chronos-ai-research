from __future__ import annotations

from src.services import integrations_service as svc


def test_get_integrations_status_shape():
    payload = svc.get_integrations_status()
    assert payload["status"] == "ok"
    assert "generated_at" in payload
    assert isinstance(payload["brokers"], list)
    assert {row["broker"] for row in payload["brokers"]} == {"binance", "deriv", "ftmo"}


def test_binance_missing_credentials_returns_offline(monkeypatch):
    monkeypatch.delenv("BINANCE_TESTNET_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_TESTNET_API_SECRET", raising=False)
    result = svc.test_binance_connection(None, None)
    assert result["ok"] is False
    assert result["broker"] == "binance"
    assert "Missing Binance credentials" in result["message"]


def test_deriv_missing_token_returns_offline(monkeypatch):
    monkeypatch.delenv("DERIV_API_TOKEN", raising=False)
    result = svc.test_deriv_connection(None)
    assert result["ok"] is False
    assert result["broker"] == "deriv"
    assert "Missing Deriv token" in result["message"]


def test_ftmo_missing_key_returns_offline(monkeypatch):
    monkeypatch.delenv("FTMO_API_KEY", raising=False)
    result = svc.test_ftmo_connection(None)
    assert result["ok"] is False
    assert result["broker"] == "ftmo"
    assert "Missing FTMO API key" in result["message"]
