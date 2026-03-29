import json
import logging
from datetime import datetime, timedelta

import os

from src.adapters.deriv_data import (
    DerivConfig,
    fetch_deriv_ohlc,
    get_active_deriv_symbols,
    fetch_deriv_ohlc_sync,
)


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


# ---------------------------------------------------------------------------
# Tests for new Phase-1 functions: get_active_deriv_symbols, fetch_deriv_ohlc_sync
# ---------------------------------------------------------------------------


class DummyCfg:
    app_id = "1"
    api_token = "tok"


def test_get_active_deriv_symbols_returns_list(monkeypatch):
    """get_active_deriv_symbols should return symbol code strings from Deriv response."""
    responses = [
        {"authorized": True},
        {"active_symbols": [{"symbol": "R_10"}, {"symbol": "R_25"}]},
    ]

    monkeypatch.setattr("websocket.create_connection", lambda url, timeout=30: FakeWS(responses))

    symbols = get_active_deriv_symbols(cfg=DummyCfg())
    assert isinstance(symbols, list)
    assert "R_10" in symbols
    assert "R_25" in symbols


def test_get_active_deriv_symbols_returns_empty_on_error(monkeypatch):
    """get_active_deriv_symbols should return [] and log a warning on WS error."""
    responses = [
        {"authorized": True},
        {"error": {"message": "service unavailable"}},
    ]

    monkeypatch.setattr("websocket.create_connection", lambda url, timeout=30: FakeWS(responses))

    symbols = get_active_deriv_symbols(cfg=DummyCfg())
    assert symbols == []


def test_fetch_deriv_ohlc_sync_returns_candle_list(monkeypatch):
    """fetch_deriv_ohlc_sync should return a correctly formatted List[Candle]."""
    epoch = int(datetime.utcnow().timestamp())
    fake_candles_data = [
        {"epoch": epoch - 3600, "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1},
        {"epoch": epoch, "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2},
    ]

    # Skip live active-symbols validation; symbol is treated as valid
    monkeypatch.setattr(
        "src.adapters.deriv_data.get_active_deriv_symbols",
        lambda cfg=None: ["R_10"],
    )
    # Provide WS responses for the candles fetch (auth + candles)
    responses = [
        {"authorized": True},
        {"candles": fake_candles_data},
    ]
    monkeypatch.setattr("websocket.create_connection", lambda url, timeout=30: FakeWS(responses))

    result = fetch_deriv_ohlc_sync("R_10", "1h", cfg=DummyCfg())

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0].open == 1.0
    assert result[1].close == 1.2
    assert result[0].timestamp < result[1].timestamp


def test_fetch_deriv_ohlc_sync_warns_on_shallow_history(monkeypatch, caplog):
    """fetch_deriv_ohlc_sync must log a WARNING (not raise) when fewer candles are
    returned than the lookback_days window requires, but still return what it got."""
    epoch = int(datetime.utcnow().timestamp())
    # 2 candles << ~2400 expected for 1h with 100-day lookback
    fake_candles_data = [
        {"epoch": epoch - 3600, "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1},
        {"epoch": epoch, "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2},
    ]

    monkeypatch.setattr(
        "src.adapters.deriv_data.get_active_deriv_symbols",
        lambda cfg=None: ["R_10"],
    )
    responses = [
        {"authorized": True},
        {"candles": fake_candles_data},
    ]
    monkeypatch.setattr("websocket.create_connection", lambda url, timeout=30: FakeWS(responses))

    with caplog.at_level(logging.WARNING, logger="src.adapters.deriv_data"):
        result = fetch_deriv_ohlc_sync("R_10", "1h", cfg=DummyCfg())

    # Must return what was fetched, not raise
    assert len(result) == 2
    # A warning containing relevant context must have been emitted
    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "shallower" in m or "fewer" in m or "shallow" in m for m in warning_messages
    ), f"Expected shallow-history warning, got: {warning_messages}"


def test_fetch_deriv_ohlc_sync_uses_correct_granularity(monkeypatch):
    """fetch_deriv_ohlc_sync must map the interval string to the correct Deriv
    granularity seconds in the ticks_history request (e.g. '4h' → 14400)."""
    epoch = int(datetime.utcnow().timestamp())
    fake_candles_data = [
        {"epoch": epoch, "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1},
    ]

    monkeypatch.setattr(
        "src.adapters.deriv_data.get_active_deriv_symbols",
        lambda cfg=None: ["R_10"],
    )

    sent_messages = []

    class CapturingFakeWS:
        def __init__(self):
            self._responses = iter([
                json.dumps({"authorized": True}),
                json.dumps({"candles": fake_candles_data}),
            ])

        def send(self, msg):
            sent_messages.append(json.loads(msg))

        def recv(self):
            return next(self._responses)

        def close(self):
            pass

    monkeypatch.setattr("websocket.create_connection", lambda url, timeout=30: CapturingFakeWS())

    fetch_deriv_ohlc_sync("R_10", "4h", cfg=DummyCfg())

    history_req = next((m for m in sent_messages if "ticks_history" in m), None)
    assert history_req is not None, "ticks_history request was not sent"
    assert history_req["granularity"] == 14400, (
        f"Expected granularity=14400 for '4h', got {history_req.get('granularity')}"
    )


def test_fetch_deriv_ohlc_sync_unknown_symbol_warns_and_returns_empty(monkeypatch, caplog):
    """fetch_deriv_ohlc_sync must log a WARNING and return [] for unknown symbols."""
    # active symbols do NOT include "UNKNOWN_SYM"
    monkeypatch.setattr(
        "src.adapters.deriv_data.get_active_deriv_symbols",
        lambda cfg=None: ["R_10", "R_25"],
    )

    with caplog.at_level(logging.WARNING, logger="src.adapters.deriv_data"):
        result = fetch_deriv_ohlc_sync("UNKNOWN_SYM", "1h", cfg=DummyCfg())

    assert result == []
    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("UNKNOWN_SYM" in m for m in warning_messages), (
        f"Expected symbol warning mentioning 'UNKNOWN_SYM', got: {warning_messages}"
    )


def test_fetch_deriv_ohlc_sync_invalid_interval_raises():
    """fetch_deriv_ohlc_sync must raise ValueError for an unsupported interval."""
    import pytest

    with pytest.raises(ValueError, match="Unsupported interval"):
        fetch_deriv_ohlc_sync("R_10", "3h", cfg=DummyCfg())
