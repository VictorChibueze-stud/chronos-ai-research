from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routers import integrations


def test_integrations_status_endpoint():
    app = FastAPI()
    app.include_router(integrations.router)
    client = TestClient(app)
    response = client.get("/api/integrations/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert {row["broker"] for row in payload["brokers"]} == {"binance", "deriv", "ftmo"}


def test_integrations_test_endpoints_with_missing_payload_credentials(monkeypatch):
    monkeypatch.delenv("BINANCE_TESTNET_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_TESTNET_API_SECRET", raising=False)
    monkeypatch.delenv("DERIV_API_TOKEN", raising=False)
    monkeypatch.delenv("FTMO_API_KEY", raising=False)
    app = FastAPI()
    app.include_router(integrations.router)
    client = TestClient(app)

    binance = client.post("/api/integrations/binance/test", json={})
    assert binance.status_code == 200
    assert binance.json()["ok"] is False
    assert binance.json()["broker"] == "binance"

    deriv = client.post("/api/integrations/deriv/test", json={})
    assert deriv.status_code == 200
    assert deriv.json()["ok"] is False
    assert deriv.json()["broker"] == "deriv"

    ftmo = client.post("/api/integrations/ftmo/test", json={})
    assert ftmo.status_code == 200
    assert ftmo.json()["ok"] is False
    assert ftmo.json()["broker"] == "ftmo"
