from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.core.features import Candle
from src.core.signals import Signal
from src.execution.signal_bridge import signal_to_intent, trend_snapshot_to_signal


def _candles_uptrend(n: int = 40) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out: list[Candle] = []
    p = 100.0
    for i in range(n):
        o, c = p, p + 0.5
        h, low = max(o, c) + 0.1, min(o, c) - 0.1
        out.append(
            Candle(
                timestamp=start + timedelta(hours=i),
                open=o,
                high=h,
                low=low,
                close=c,
                volume=1.0,
            )
        )
        p = c
    return out


def test_signal_to_intent_open_long():
    sig = Signal(status="open", direction="long", entry_price=1.0, size=2.0)
    intent = signal_to_intent(sig, symbol="R_10", stake_amount=3.0)
    assert intent is not None
    assert intent.symbol == "R_10"
    assert intent.side == "long"
    assert intent.stake_amount == 3.0


def test_signal_to_intent_no_trade():
    assert signal_to_intent(Signal(status="no_trade"), symbol="R_10") is None


def test_trend_snapshot_returns_signal():
    candles = _candles_uptrend(80)
    sig = trend_snapshot_to_signal(candles)
    assert sig.status in {"open", "no_trade"}
