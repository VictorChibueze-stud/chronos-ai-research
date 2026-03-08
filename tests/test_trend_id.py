"""Tests for src/core/trend_id.py — identify_trend()."""
from datetime import datetime, timedelta
from src.core.features import Candle
from src.core.trend_id import identify_trend

def _make_candles(prices: list) -> list:
    """Build minimal Candle list from a sequence of close/high/low prices."""
    base = datetime(2024, 1, 1)
    return [
        Candle(
            timestamp=base + timedelta(hours=i),
            open=p, high=p, low=p, close=p, volume=100
        ) for i, p in enumerate(prices)
    ]

def test_clear_downtrend():
    prices = [100, 98, 99, 96, 97, 93, 95, 90, 92, 88, 89, 85]
    # min_swing_candles=1 required because dataset is so small
    result = identify_trend(_make_candles(prices), min_swing_candles=1)
    
    assert result["trend"] == "down"
    assert len(result["legs"]) >= 2
    assert result["legs"][0]["type"] == "impulse"
    assert result["legs"][0]["slope"] < 0

def test_clear_uptrend():
    prices = [80, 82, 81, 85, 83, 88, 86, 92, 90, 95]
    result = identify_trend(_make_candles(prices), min_swing_candles=1)
    
    assert result["trend"] == "up"
    assert result["legs"][0]["slope"] is not None
    assert result["legs"][0]["slope"] > 0

def test_flat_range():
    prices = [100, 101, 99, 100, 101, 99, 100, 101, 99, 100]
    result = identify_trend(_make_candles(prices), min_swing_candles=1)
    
    assert result["trend"] == "range"