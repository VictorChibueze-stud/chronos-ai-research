"""Signal and strategy interface definitions for Ikenga backtests.

This module defines simple, serializable dataclasses and a protocol that
strategies should implement when used with the backtest engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Protocol


Direction = Literal["long", "short"]


@dataclass
class Signal:
	"""Deterministic strategy output for a single instrument on a single bar.

	- status: "no_trade" means do nothing new; "open" means open a new position;
			  "close" means close an existing position at bar close.
	- direction: required when status == "open".
	- entry_price / stop_loss_price / take_profit_price: levels the strategy suggests.
	- size: number of units/contracts (default 1.0).
	- metadata: free-form diagnostics.
	"""
	status: Literal["no_trade", "open", "close"] = "no_trade"
	direction: Optional[Direction] = None
	entry_price: Optional[float] = None
	stop_loss_price: Optional[float] = None
	take_profit_price: Optional[float] = None
	size: float = 1.0
	metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyContext:
	"""Information passed to the strategy on each bar."""
	index: int
	timestamp: datetime
	timeframe: str
	candles_window: Any
	features: Dict[str, Any]
	has_open_position: bool
	open_direction: Optional[Direction]
	open_entry_price: Optional[float]


class StrategyFn(Protocol):
	def __call__(self, ctx: StrategyContext) -> Signal:
		...

