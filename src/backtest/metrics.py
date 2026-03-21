"""Stub module to be implemented in later phases."""

from dataclasses import dataclass
from typing import List

from src.backtest.engine import BacktestTrade

@dataclass
class EquityMetrics:
	total_pnl: float
	num_trades: int
	win_rate: float
	avg_pnl_per_trade: float
	max_drawdown: float


def compute_equity_metrics(trades: List[BacktestTrade]) -> EquityMetrics:
	if not trades:
		return EquityMetrics(
			total_pnl=0.0,
			num_trades=0,
			win_rate=0.0,
			avg_pnl_per_trade=0.0,
			max_drawdown=0.0,
		)

	pnls = [t.pnl for t in trades]
	total_pnl = sum(pnls)
	num_trades = len(trades)
	wins = sum(1 for p in pnls if p > 0)
	win_rate = wins / num_trades if num_trades > 0 else 0.0
	avg_pnl = total_pnl / num_trades if num_trades > 0 else 0.0

	equity = 0.0
	peak = 0.0
	max_dd = 0.0
	for p in pnls:
		equity += p
		if equity > peak:
			peak = equity
		drawdown = peak - equity
		if drawdown > max_dd:
			max_dd = drawdown

	return EquityMetrics(
		total_pnl=total_pnl,
		num_trades=num_trades,
		win_rate=win_rate,
		avg_pnl_per_trade=avg_pnl,
		max_drawdown=max_dd,
	)
