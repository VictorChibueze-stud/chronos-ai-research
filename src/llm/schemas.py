from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, confloat


class MomentumState(BaseModel):
    rsi: float
    state: Literal["overbought", "oversold", "neutral"]


class TrendState(BaseModel):
    direction: Literal["up", "down", "sideways"]
    strength: confloat(ge=0.0, le=100.0)
    ema_alignment: Literal["bullish", "bearish", "mixed"]


class VolatilityState(BaseModel):
    atr_value: float
    regime: Literal["low", "normal", "high"]


class StructureState(BaseModel):
    recent_swing_high: Optional[float] = None
    recent_swing_low: Optional[float] = None
    dist_to_support_pct: float


class MarketSnapshot(BaseModel):
    symbol: str
    timeframe: str
    timestamp: str
    price: float
    trend: TrendState
    momentum: MomentumState
    volatility: VolatilityState
    structure: StructureState
    recent_events: List[str] = Field(default_factory=list)


class LongTermSummary(BaseModel):
    regime_history: List[Dict[str, Any]]
    key_levels: Dict[str, float]
    volatility_context: Dict[str, Any]


class InstrumentInfo(BaseModel):
    symbol: str
    pip_size: float
    pip_value_per_lot: float
    min_lot: float
    max_lot: float
    lot_step: float

    class Config:
        extra = "forbid"
