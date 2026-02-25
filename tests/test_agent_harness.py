import json
from datetime import datetime

import pytest

from src.agent.harness import AgentHarness
from src.core.features import Candle


def _mock_fetch(symbol, gran, start, end):
    # return a small list of candles
    now = datetime.utcnow()
    return [Candle(timestamp=now, open=1.0, high=1.2, low=0.9, close=1.1, volume=0.0)]


def test_collect_context_and_generate_prompt(monkeypatch):
    monkeypatch.setattr("src.agent.harness.fetch_deriv_ohlc", _mock_fetch)
    h = AgentHarness("R_10")
    ctx = h.collect_context()
    assert isinstance(ctx, str)
    parsed = json.loads(ctx)
    assert "snapshots" in parsed
    assert parsed["symbol"] == "R_10"

    prompt = h.generate_prompt()
    assert "Risk-Averse Trend Following Agent" in prompt
    assert "CURRENT MARKET DATA:" in prompt
    assert "snapshots" in prompt
