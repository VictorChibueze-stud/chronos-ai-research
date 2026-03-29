from datetime import datetime, timedelta, timezone
import logging

import pandas as pd
from src.core.features import Candle
from src.scanner.market_scanner import RESULT_FIELDS, fetch_top_symbols, run_pipeline, run_scanner


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


def _flat_candles(n: int = 80, base: float = 100.0, vol: float = 10.0) -> list[Candle]:
    start_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out: list[Candle] = []
    for i in range(n):
        out.append(
            Candle(
                timestamp=start_ts + timedelta(hours=i),
                open=base,
                high=base + 1.0,
                low=base - 1.0,
                close=base + (0.1 if i % 2 == 0 else -0.1),
                volume=vol,
            )
        )
    return out


def test_run_scanner_routes_by_symbols_yaml_and_applies_correlation_filter(monkeypatch):
    symbols_cfg = {
        "binance": {"BTC/USDT": "BTCUSDT", "ETH/USDT": "ETHUSDT"},
        "deriv": {"Volatility 10 Index": "R_10", "Volatility 25 Index": "R_25"},
    }

    monkeypatch.setattr(
        "src.scanner.market_scanner._load_symbols_config",
        lambda: symbols_cfg,
    )

    binance_calls = []
    deriv_calls = []
    active_calls = {"count": 0}

    def _fake_binance_fetch(symbol, interval, start_time=None):
        binance_calls.append((symbol, interval))
        return _flat_candles(base=100.0, vol=200.0)

    def _fake_deriv_fetch(symbol, interval, start_time=None):
        deriv_calls.append((symbol, interval))
        return _flat_candles(base=50.0, vol=0.0)

    def _fake_get_active_deriv_symbols():
        active_calls["count"] += 1
        return ["R_10"]

    monkeypatch.setattr("src.scanner.market_scanner.fetch_binance_ohlc_sync", _fake_binance_fetch)
    monkeypatch.setattr("src.scanner.market_scanner.fetch_deriv_ohlc_sync", _fake_deriv_fetch)
    monkeypatch.setattr(
        "src.scanner.market_scanner.get_active_deriv_symbols",
        _fake_get_active_deriv_symbols,
    )

    def _fake_run_pipeline(symbol, interval, candles, **kwargs):
        return {
            "symbol": symbol,
            "interval": interval,
            "trend": "up",
            "current_phase": "impulse",
            "confirmed_leg_count": 2,
            "impulse_count": 1,
            "retracement_count": 1,
            "mean_impulse_move_pct": 2.0,
            "mean_retracement_depth_pct": 40.0,
            "mean_impulse_duration_candles": 10.0,
            "mean_retracement_duration_candles": 6.0,
            "velocity_trend": "stable",
            "choch_intact": True,
            "bos_count": 1,
            "any_choch_risk": False,
            "anomalous": False,
            "candle_count": len(candles),
            "first_candle_ts": candles[0].timestamp.isoformat(),
            "last_candle_ts": candles[-1].timestamp.isoformat(),
            "error": None,
        }

    monkeypatch.setattr("src.scanner.market_scanner.run_pipeline", _fake_run_pipeline)

    def _fake_corr(results_df, symbol_candle_map):
        # Ensure the unified candle map uses tuple keys: (symbol, interval)
        assert all(isinstance(k, tuple) and len(k) == 2 for k in symbol_candle_map.keys())
        # Keep only one row to prove the filter is applied before return.
        return results_df.head(1).copy()

    monkeypatch.setattr(
        "src.scanner.market_scanner.compute_correlation_groups",
        _fake_corr,
    )

    out = run_scanner(
        symbols=["BTCUSDT", "ETHUSDT"],
        intervals=["1h", "4h"],
        filter_config={},
        force_full=False,
    )

    assert isinstance(out, pd.DataFrame)
    assert len(out) == 1
    assert active_calls["count"] == 1
    assert set(binance_calls) == {
        ("BTCUSDT", "1h"),
        ("BTCUSDT", "4h"),
        ("ETHUSDT", "1h"),
        ("ETHUSDT", "4h"),
    }
    # R_25 is inactive and must be dropped.
    assert set(deriv_calls) == {
        ("R_10", "1h"),
        ("R_10", "4h"),
    }


def test_run_scanner_warns_and_drops_missing_deriv_symbols(monkeypatch, caplog):
    symbols_cfg = {
        "deriv": {"Volatility 10 Index": "R_10", "Volatility 25 Index": "R_25"}
    }
    monkeypatch.setattr("src.scanner.market_scanner._load_symbols_config", lambda: symbols_cfg)

    monkeypatch.setattr("src.scanner.market_scanner.fetch_binance_ohlc_sync", lambda *a, **k: [])
    deriv_calls = []
    monkeypatch.setattr(
        "src.scanner.market_scanner.fetch_deriv_ohlc_sync",
        lambda symbol, interval, start_time=None: deriv_calls.append((symbol, interval)) or _flat_candles(),
    )
    monkeypatch.setattr("src.scanner.market_scanner.get_active_deriv_symbols", lambda: ["R_10"])
    monkeypatch.setattr(
        "src.scanner.market_scanner.run_pipeline",
        lambda symbol, interval, candles, **kwargs: {
            field: None for field in RESULT_FIELDS
        } | {"symbol": symbol, "interval": interval, "error": None},
    )
    monkeypatch.setattr(
        "src.scanner.market_scanner.compute_correlation_groups",
        lambda df, m: df,
    )

    with caplog.at_level(logging.WARNING, logger="src.scanner.market_scanner"):
        run_scanner(
            symbols=["R_10", "R_25"],
            intervals=["1h"],
            filter_config={},
            force_full=False,
        )

    assert deriv_calls == [("R_10", "1h")]
    assert any("R_25" in rec.message for rec in caplog.records)
