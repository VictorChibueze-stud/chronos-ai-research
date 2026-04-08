from __future__ import annotations

from typing import Any, Literal

from src.core.filter_defaults import SCAN_AND_ANALYSIS_FILTER_DEFAULTS
from src.core.signals import Signal
from src.core.trend_id import identify_trend
from src.execution.contracts import NormalizedOrderIntent, ProviderId


def trend_snapshot_to_signal(candles: list[Any], filter_kw: dict[str, Any] | None = None) -> Signal:
    """Map latest trend identification to a simple open/no_trade signal (impulse continuation)."""
    kw = dict(SCAN_AND_ANALYSIS_FILTER_DEFAULTS)
    if filter_kw:
        kw.update(filter_kw)
    result = identify_trend(candles, **kw)
    trend = (result.get("trend") or "range").lower()
    phase = (result.get("current_phase") or "range").lower()
    last_close = float(candles[-1].close) if candles else 0.0

    if phase == "impulse" and trend == "up":
        return Signal(
            status="open",
            direction="long",
            entry_price=last_close,
            size=1.0,
            metadata={"source": "trend_snapshot", "trend": trend, "phase": phase},
        )
    if phase == "impulse" and trend == "down":
        return Signal(
            status="open",
            direction="short",
            entry_price=last_close,
            size=1.0,
            metadata={"source": "trend_snapshot", "trend": trend, "phase": phase},
        )
    return Signal(
        status="no_trade",
        metadata={"source": "trend_snapshot", "trend": trend, "phase": phase},
    )


def signal_to_intent(
    signal: Signal,
    *,
    symbol: str,
    stake_amount: float = 10.0,
    provider: ProviderId = ProviderId.DERIV,
    duration: int = 5,
    duration_unit: Literal["t", "s", "m", "h", "d"] = "t",
) -> NormalizedOrderIntent | None:
    if signal.status != "open" or signal.direction is None:
        return None
    return NormalizedOrderIntent(
        provider=provider,
        symbol=symbol,
        side=signal.direction,
        stake_amount=stake_amount,
        duration=duration,
        duration_unit=duration_unit,
        metadata=dict(signal.metadata or {}),
    )
