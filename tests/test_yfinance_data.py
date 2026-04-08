"""Unit tests for Yahoo Finance adapter (mocked download)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
import pytest

from src.adapters.yfinance_data import (
    YFINANCE_SYMBOL_MAP,
    fetch_yfinance_ohlc_sync,
    is_yfinance_symbol,
)


def test_is_yfinance_symbol() -> None:
    assert is_yfinance_symbol("SPX500") is True
    assert is_yfinance_symbol("spx500") is True
    assert is_yfinance_symbol("BTCUSDT") is False


def test_unknown_symbol_raises() -> None:
    with pytest.raises(ValueError, match="Unknown yfinance"):
        fetch_yfinance_ohlc_sync("NOTINMAP", "1d")


def test_unknown_interval_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported yfinance interval"):
        fetch_yfinance_ohlc_sync("SPX500", "2h")


@patch("src.adapters.yfinance_data.yf.download")
def test_fetch_maps_to_candles(mock_download) -> None:
    idx = pd.DatetimeIndex(
        [pd.Timestamp("2024-01-02", tz="UTC"), pd.Timestamp("2024-01-03", tz="UTC")]
    )
    mock_download.return_value = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.5],
            "Close": [101.5, 102.0],
            "Volume": [1e6, 2e6],
        },
        index=idx,
    )
    candles = fetch_yfinance_ohlc_sync("SPX500", "1d", start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))
    assert len(candles) == 2
    assert candles[0].open == 100.0
    assert candles[1].close == 102.0
    mock_download.assert_called_once()
    call_kw = mock_download.call_args.kwargs
    assert call_kw["tickers"] == YFINANCE_SYMBOL_MAP["SPX500"]
    assert call_kw["interval"] == "1d"


@patch("src.adapters.yfinance_data.yf.download")
def test_fetch_4h_uses_hourly_then_resamples(mock_download) -> None:
    hours = pd.date_range("2024-01-01", periods=8, freq="h", tz="UTC")
    mock_download.return_value = pd.DataFrame(
        {
            "Open": [float(i) for i in range(8)],
            "High": [float(i) + 0.5 for i in range(8)],
            "Low": [float(i) - 0.5 for i in range(8)],
            "Close": [float(i) + 0.25 for i in range(8)],
            "Volume": [1.0] * 8,
        },
        index=hours,
    )
    candles = fetch_yfinance_ohlc_sync("SPX500", "4h", start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))
    assert mock_download.call_args.kwargs["interval"] == "1h"
    assert len(candles) == 2
    assert candles[0].open == 0.0
    assert candles[1].open == 4.0
