from datetime import timedelta, datetime

import pytest

from src.core.features import Candle
from src.llm.context import build_snapshot, build_long_term_summary, get_instrument_info


def make_candles(start: datetime, n: int, start_price: float = 1.0, step: float = 1.0):
    candles = []
    price = start_price
    for i in range(n):
        o = price
        c = price + step
        h = max(o, c) + 0.1
        l = min(o, c) - 0.1
        candles.append(Candle(timestamp=start + timedelta(days=i), open=o, high=h, low=l, close=c, volume=100.0))
        price = c
    return candles


def test_snapshot_overbought():
    start = datetime.utcnow() - timedelta(days=30)
    candles = make_candles(start, 30, start_price=1.0, step=1.0)
    snap = build_snapshot(candles, timeframe="1D")
    assert snap.momentum.state == "overbought"
    # JSON serializable via dict
    d = snap.dict()
    assert isinstance(d["symbol"], str)
    assert isinstance(d["price"], float)


def test_long_term_summary_52w():
    start = datetime.utcnow() - timedelta(days=365)
    # create 365 candles with rising highs
    candles = []
    for i in range(365):
        base = 100.0 + i * 0.5
        candles.append(Candle(timestamp=start + timedelta(days=i), open=base, high=base + 1.0, low=base - 1.0, close=base + 0.5))
    summary = build_long_term_summary(candles)
    assert len(summary.regime_history) > 0
    assert summary.key_levels["52w_high"] == max(c.high for c in candles)


def test_get_instrument_info_r10():
    info = get_instrument_info("R_10")
    assert info.pip_size == 0.01
    assert info.symbol == "R_10"
