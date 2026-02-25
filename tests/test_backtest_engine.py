from datetime import datetime, timedelta

from src.core.features import Candle
from src.core.signals import Signal
from src.backtest.engine import run_backtest_single_symbol, BacktestConfig
from src.backtest.metrics import compute_equity_metrics


def make_candles(n=10, start=None, step_minutes=15):
    if start is None:
        start = datetime.utcnow()
    rows = []
    for i in range(n):
        t = start + timedelta(minutes=i * step_minutes)
        o = float(i)
        c = float(i)
        rows.append(Candle(timestamp=t, open=o, high=c + 0.5, low=c - 0.5, close=c, volume=0.0))
    return rows


def test_backtest_no_trades():
    candles = make_candles(10)

    def strat(ctx):
        return Signal(status="no_trade")

    result = run_backtest_single_symbol(candles, strat, BacktestConfig())
    assert len(result.trades) == 0
    assert result.starting_equity == result.ending_equity


def test_backtest_simple_long():
    # increasing prices
    candles = []
    base = datetime.utcnow()
    for i in range(10):
        t = base + timedelta(minutes=i)
        o = float(i)
        c = float(i)
        candles.append(Candle(timestamp=t, open=o, high=c + 0.2, low=c - 0.2, close=c, volume=0.0))

    def strat(ctx):
        # open at index 1
        if not ctx.has_open_position and ctx.index == 1:
            price = ctx.candles_window[-1].close
            return Signal(status="open", direction="long", entry_price=price, stop_loss_price=price - 1000, take_profit_price=price + 1000, size=1.0)
        # close at index 4
        if ctx.has_open_position and ctx.index == 4:
            return Signal(status="close")
        return Signal(status="no_trade")

    result = run_backtest_single_symbol(candles, strat, BacktestConfig())
    assert len(result.trades) >= 1
    metrics = compute_equity_metrics(result.trades)
    assert metrics.total_pnl > 0
    assert metrics.win_rate > 0
