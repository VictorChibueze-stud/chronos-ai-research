import json
from datetime import datetime, timedelta

from src.core.features import Candle
from src.llm.context import build_single_snapshot, build_multi_snapshot


def make_candles(start: datetime, n: int, start_price: float = 1.0, step: float = 0.5):
    candles = []
    price = start_price
    for i in range(n):
        o = price
        c = price + step
        h = max(o, c) + 0.05
        l = min(o, c) - 0.05
        candles.append(Candle(timestamp=start + timedelta(minutes=i), open=o, high=h, low=l, close=c, volume=100.0))
        price = c
    return candles


def test_build_single_snapshot_json_serializable():
    start = datetime.utcnow() - timedelta(hours=1)
    candles = make_candles(start, 20)
    snap = build_single_snapshot(candles, "15m")
    # should be JSON serializable
    s = json.dumps(snap.dict())
    assert isinstance(s, str)
    assert isinstance(snap.symbol, str)
    assert hasattr(snap, "trend")
    assert isinstance(snap.momentum.rsi, float)


def test_build_multi_snapshot_nesting():
    start = datetime.utcnow() - timedelta(hours=4)
    c15 = make_candles(start, 50, start_price=1.0, step=0.1)
    c4h = make_candles(start, 20, start_price=2.0, step=0.2)
    out = build_multi_snapshot({"15m": c15, "4h": c4h})
    assert "15m" in out and "4h" in out
    assert isinstance(out["4h"].price, float)
