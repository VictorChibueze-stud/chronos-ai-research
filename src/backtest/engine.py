"""Single-symbol backtest engine for Ikenga.

This engine runs a deterministic, discrete-bar backtest using a pluggable
`StrategyFn`. It supports one open position at a time and computes simple
trade records and an equity curve.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from src.core.features import Candle, compute_price_features
from src.core.signals import Signal, StrategyFn, Direction, StrategyContext


@dataclass
class BacktestConfig:
	initial_equity: float = 10_000.0
	commission_per_trade: float = 0.0
	slippage_pct: float = 0.0
	timeframe: str = "15m"
	max_lookback: int = 500


@dataclass
class BacktestTrade:
	direction: Direction
	entry_time: datetime
	exit_time: datetime
	entry_price: float
	exit_price: float
	size: float
	pnl: float
	max_adverse_excursion: float
	max_favorable_excursion: float


@dataclass
class BacktestResult:
	config: BacktestConfig
	starting_equity: float
	ending_equity: float
	equity_curve: List[float]
	timestamps: List[datetime]
	trades: List[BacktestTrade]


def _apply_slippage(price: float, slippage_pct: float, direction: Direction, side: str) -> float:
	# side: 'entry' or 'exit'
	if slippage_pct <= 0:
		return price
	if direction == "long":
		if side == "entry":
			return price * (1.0 + slippage_pct)
		else:
			return price * (1.0 - slippage_pct)
	else:
		# short
		if side == "entry":
			return price * (1.0 - slippage_pct)
		else:
			return price * (1.0 + slippage_pct)


def run_backtest_single_symbol(
	candles: List[Candle],
	strategy_fn: StrategyFn,
	config: Optional[BacktestConfig] = None,
) -> BacktestResult:
	if config is None:
		config = BacktestConfig()

	if len(candles) < 2:
		return BacktestResult(
			config=config,
			starting_equity=config.initial_equity,
			ending_equity=config.initial_equity,
			equity_curve=[config.initial_equity],
			timestamps=[candles[0].timestamp] if candles else [],
			trades=[],
		)

	equity = config.initial_equity
	equity_curve: List[float] = []
	timestamps: List[datetime] = []
	trades: List[BacktestTrade] = []

	position_open = False
	position_direction: Optional[Direction] = None
	position_entry_price: Optional[float] = None
	position_size: float = 0.0
	position_entry_time: Optional[datetime] = None
	position_sl: Optional[float] = None
	position_tp: Optional[float] = None
	mae = 0.0
	mfe = 0.0

	for i in range(len(candles)):
		window = candles[max(0, i - config.max_lookback + 1) : i + 1]
		feats = compute_price_features(window, timeframe=config.timeframe, max_lookback=config.max_lookback)

		ctx = StrategyContext(
			index=i,
			timestamp=candles[i].timestamp,
			timeframe=config.timeframe,
			candles_window=window,
			features=feats,
			has_open_position=position_open,
			open_direction=position_direction,
			open_entry_price=position_entry_price,
		)

		sig = strategy_fn(ctx)

		bar = candles[i]

		# If there's an open position, check for SL/TP within this bar first
		if position_open:
			sl_hit = position_sl is not None and (bar.low <= position_sl <= bar.high)
			tp_hit = position_tp is not None and (bar.low <= position_tp <= bar.high)

			closed = False
			exit_price = None
			exit_time = bar.timestamp

			if sl_hit and tp_hit:
				# conservative: assume stop-loss first
				exit_price = position_sl
				closed = True
			elif sl_hit:
				exit_price = position_sl
				closed = True
			elif tp_hit:
				exit_price = position_tp
				closed = True
			elif sig.status == "close":
				exit_price = bar.close
				closed = True

			if closed and exit_price is not None:
				exit_price = _apply_slippage(exit_price, config.slippage_pct, position_direction, "exit")
				raw_pnl = (exit_price - position_entry_price) * position_size if position_direction == "long" else (position_entry_price - exit_price) * position_size
				pnl = raw_pnl - config.commission_per_trade

				trades.append(
					BacktestTrade(
						direction=position_direction,
						entry_time=position_entry_time,
						exit_time=exit_time,
						entry_price=position_entry_price,
						exit_price=exit_price,
						size=position_size,
						pnl=pnl,
						max_adverse_excursion=mae,
						max_favorable_excursion=mfe,
					)
				)
				equity += pnl
				position_open = False
				position_direction = None
				position_entry_price = None
				position_size = 0.0
				position_entry_time = None
				position_sl = None
				position_tp = None
				mae = 0.0
				mfe = 0.0

		# If no open position, consider opening based on signal
		if not position_open and sig.status == "open":
			entry_price = sig.entry_price if sig.entry_price is not None else bar.close
			entry_price = _apply_slippage(entry_price, config.slippage_pct, sig.direction, "entry")
			position_open = True
			position_direction = sig.direction
			position_entry_price = entry_price
			position_size = sig.size
			position_entry_time = bar.timestamp
			position_sl = sig.stop_loss_price
			position_tp = sig.take_profit_price
			mae = 0.0
			mfe = 0.0

		# update excursions while position is open
		if position_open:
			if position_direction == "long":
				mfe = max(mfe, bar.high - position_entry_price)
				mae = max(mae, position_entry_price - bar.low)
			else:
				mfe = max(mfe, position_entry_price - bar.low)
				mae = max(mae, bar.high - position_entry_price)

		equity_curve.append(equity)
		timestamps.append(bar.timestamp)

	# close any remaining open position at last close
	if position_open and position_entry_price is not None:
		last = candles[-1]
		exit_price = _apply_slippage(last.close, config.slippage_pct, position_direction, "exit")
		raw_pnl = (exit_price - position_entry_price) * position_size if position_direction == "long" else (position_entry_price - exit_price) * position_size
		pnl = raw_pnl - config.commission_per_trade
		trades.append(
			BacktestTrade(
				direction=position_direction,
				entry_time=position_entry_time,
				exit_time=last.timestamp,
				entry_price=position_entry_price,
				exit_price=exit_price,
				size=position_size,
				pnl=pnl,
				max_adverse_excursion=mae,
				max_favorable_excursion=mfe,
			)
		)
		equity += pnl
		equity_curve[-1] = equity

	return BacktestResult(
		config=config,
		starting_equity=config.initial_equity,
		ending_equity=equity,
		equity_curve=equity_curve,
		timestamps=timestamps,
		trades=trades,
	)

