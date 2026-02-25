"""Deterministic LLM tools for proposing trade levels and sizing.

These functions are pure, stateless, and enforce hard risk guardrails so the
LLM is only responsible for high-level reasoning. All numeric outputs are
standard Python types and fully typed.
"""
from __future__ import annotations

from typing import Dict, Any, Literal


def propose_trade_levels(
    direction: Literal["long", "short"],
    entry_price: float,
    atr: float,
    risk_reward: float = 3.0,
) -> Dict[str, Any]:
    """Propose entry, stop loss and take profit levels.

    - stop_loss_distance = 1.5 * atr
    - take_profit_distance = stop_loss_distance * risk_reward

    Returns dict with direction, entry, stop_loss, take_profit, rr_achieved.
    """
    if atr < 0:
        raise ValueError("atr must be non-negative")

    stop_loss_distance = 1.5 * float(atr)
    take_profit_distance = stop_loss_distance * float(risk_reward)

    entry = float(entry_price)
    if direction == "long":
        stop_loss = entry - stop_loss_distance
        take_profit = entry + take_profit_distance
    elif direction == "short":
        stop_loss = entry + stop_loss_distance
        take_profit = entry - take_profit_distance
    else:
        raise ValueError("direction must be 'long' or 'short'")

    rr_achieved = (abs(take_profit - entry) / abs(stop_loss - entry)) if stop_loss != entry else float("inf")

    return {
        "direction": direction,
        "entry": float(entry),
        "stop_loss": float(stop_loss),
        "take_profit": float(take_profit),
        "rr_achieved": float(rr_achieved),
    }


def position_size(
    equity: float,
    risk_pct: float,
    entry_price: float,
    stop_loss_price: float,
    pip_value: float = 1.0,
) -> Dict[str, Any]:
    """Compute position volume given equity and risk percent.

    - risk_pct is clamped to max 2.0 (%).
    - cash_at_risk = equity * (risk_pct / 100)
    - price_dist = abs(entry_price - stop_loss_price)
    - volume = cash_at_risk / (price_dist * pip_value)

    Returns dict with cash_at_risk, volume (2 decimals), capped_risk (bool).
    """
    if equity < 0:
        raise ValueError("equity must be non-negative")
    if pip_value <= 0:
        raise ValueError("pip_value must be > 0")

    capped_risk = False
    requested = float(risk_pct)
    max_allowed = 2.0
    used_risk = requested
    if requested > max_allowed:
        used_risk = max_allowed
        capped_risk = True
    if used_risk < 0:
        used_risk = 0.0

    cash_at_risk = float(equity) * (used_risk / 100.0)
    price_dist = abs(float(entry_price) - float(stop_loss_price))

    if price_dist <= 0.0:
        # avoid division by zero; cannot size position when stop equals entry
        volume = 0.0
    else:
        volume = cash_at_risk / (price_dist * float(pip_value))

    volume = round(float(volume), 2)

    return {"cash_at_risk": float(cash_at_risk), "volume": volume, "capped_risk": bool(capped_risk)}
