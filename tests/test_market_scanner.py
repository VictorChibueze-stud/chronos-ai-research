from datetime import datetime, timedelta, timezone

from src.core.features import Candle
from src.scanner.market_scanner import RESULT_FIELDS, fetch_top_symbols, run_pipeline


def _build_downtrend_candles(count: int = 100) -> list[Candle]:
    candles: list[Candle] = []
    start_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    price = 1000.0

    for idx in range(count):
        # Add slight oscillation so local highs/lows exist while preserving downtrend.
        oscillation = (idx % 6) * 0.3
        open_price = price + oscillation
        close_price = price - 1.5 + ((idx % 4) * 0.1)
        high_price = max(open_price, close_price) + 0.8
        low_price = min(open_price, close_price) - 0.8

        candles.append(
            Candle(
                timestamp=start_ts + timedelta(hours=idx),
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=1000.0 + idx,
            )
        )
        price -= 0.8

    return candles


def test_run_pipeline_returns_all_keys():
    candles = _build_downtrend_candles(100)

    result = run_pipeline("TEST", "1h", candles)

    for key in RESULT_FIELDS:
        assert key in result
    assert result["error"] is None


def test_run_pipeline_error_handling():
    result = run_pipeline("TEST", "1h", [])

    assert result["symbol"] == "TEST"
    assert result["interval"] == "1h"
    assert result["error"] is not None

    for key in RESULT_FIELDS:
        if key in {"symbol", "interval", "error"}:
            continue
        assert result[key] is None


class _MockResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_fetch_top_symbols_returns_list(monkeypatch):
    payload = [
        {"symbol": "ETHUSDT", "quoteVolume": "500"},
        {"symbol": "BTCUSDT", "quoteVolume": "1000"},
        {"symbol": "SOLUSDT", "quoteVolume": "700"},
        {"symbol": "XRPUSDT", "quoteVolume": "300"},
        {"symbol": "ADAUSDT", "quoteVolume": "200"},
    ]

    monkeypatch.setattr(
        "src.scanner.market_scanner.requests.get",
        lambda *args, **kwargs: _MockResponse(payload),
    )

    result = fetch_top_symbols(3)

    assert result == ["BTCUSDT", "SOLUSDT", "ETHUSDT"]


def test_stablecoin_filtered_out(monkeypatch):
    payload = [
        {"symbol": "USDCUSDT", "quoteVolume": "5000"},
        {"symbol": "BTCUSDT", "quoteVolume": "1000"},
        {"symbol": "ETHUSDT", "quoteVolume": "900"},
        {"symbol": "SOLUSDT", "quoteVolume": "800"},
    ]

    monkeypatch.setattr(
        "src.scanner.market_scanner.requests.get",
        lambda *args, **kwargs: _MockResponse(payload),
    )

    result = fetch_top_symbols(3)

    assert "USDCUSDT" not in result
    assert result == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
