"""
Position sizing calculator for IKENGA paper trading.
Computes lot size from account risk parameters and
contract specifications.
"""
from __future__ import annotations

import math
from typing import Optional

from sqlalchemy.orm import Session

from src.db.models import ContractSpec


def get_contract_spec(symbol: str, db: Session) -> Optional[ContractSpec]:
    """Return ContractSpec for symbol or None if not found."""
    return (
        db.query(ContractSpec)
        .filter(ContractSpec.symbol == symbol.strip().upper())
        .first()
    )


def _get_pip_value_usd(
    spec: ContractSpec,
    current_price: float,
    usd_quote_rate: Optional[float] = None,
) -> float:
    """
    Return the USD value of one pip for one standard lot.

    Logic by asset class:
    - Crypto: not applicable (returns 1.0, sizing done in quantity)
    - Synthetic: pip_size * contract_size (USD-denominated)
    - Commodity: use point_value directly
    - Forex USD-quoted (EURUSD, GBPUSD, AUDUSD, NZDUSD):
        pip_value = pip_size * contract_size
    - Forex USD-base (USDJPY, USDCHF, USDCAD etc):
        pip_value = (pip_size * contract_size) / current_price
    - Forex cross (EURJPY, GBPCHF etc):
        pip_value = (pip_size * contract_size) / usd_quote_rate
        where usd_quote_rate = current price of USD/quote_currency
    """
    if spec.is_crypto:
        return 1.0

    if spec.asset_class == "synthetic":
        return spec.pip_size * spec.contract_size

    if spec.asset_class == "commodity":
        # Use point_value which is pre-computed for $1 move per lot
        # pip_value = point_value * pip_size (since point=$1 move)
        return spec.point_value * spec.pip_size

    # Forex
    quote = (spec.quote_currency or "").upper()
    base = (spec.base_currency or "").upper()

    if quote == "USD":
        # Direct pair: EURUSD, GBPUSD, AUDUSD, NZDUSD
        return spec.pip_size * spec.contract_size

    if base == "USD":
        # Inverse pair: USDJPY, USDCHF, USDCAD
        # pip_value = (pip_size * contract_size) / current_price
        if current_price <= 0:
            return spec.pip_size * spec.contract_size
        return (spec.pip_size * spec.contract_size) / current_price

    # Cross pair: EURJPY, GBPCHF, AUDJPY etc
    # Need USD/quote rate
    if usd_quote_rate and usd_quote_rate > 0:
        return (spec.pip_size * spec.contract_size) / usd_quote_rate
    # Fallback: approximate using current_price
    # This is imprecise but safe for paper trading
    return (spec.pip_size * spec.contract_size) / current_price


def _round_to_step(value: float, step: float) -> float:
    """Round value DOWN to the nearest step increment."""
    if step <= 0:
        return value
    precision = max(0, -int(math.floor(math.log10(step))))
    result = math.floor(value / step) * step
    return round(result, precision)


def calculate_lot_size(
    symbol: str,
    account_balance_usd: float,
    risk_pct: float,
    entry_price: float,
    stop_price: float,
    db: Session,
    usd_quote_rate: Optional[float] = None,
) -> dict:
    """
    Calculate the correct lot size to risk exactly risk_pct of
    account_balance_usd on this trade.

    Returns dict with:
    - lot_size: float — the rounded lot size to use
    - risk_amount_usd: float — dollar amount being risked
    - stop_distance_pips: float — pips between entry and stop
    - pip_value_usd: float — USD value of 1 pip per lot
    - spec_found: bool — whether contract spec was found
    - error: str | None — error message if calculation failed
    """
    result = {
        "lot_size": 0.0,
        "risk_amount_usd": 0.0,
        "stop_distance_pips": 0.0,
        "pip_value_usd": 0.0,
        "spec_found": False,
        "error": None,
    }

    spec = get_contract_spec(symbol, db)
    if spec is None:
        result["error"] = f"No contract spec found for {symbol}"
        return result

    result["spec_found"] = True

    # Risk in USD
    risk_amount = account_balance_usd * (risk_pct / 100.0)
    result["risk_amount_usd"] = round(risk_amount, 2)

    # Stop distance
    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        result["error"] = "Stop distance is zero"
        return result

    if spec.is_crypto:
        # For crypto: quantity = risk_amount / stop_distance_in_quote
        # stop_distance is already in USDT terms
        raw_qty = risk_amount / stop_distance
        qty = _round_to_step(raw_qty, spec.lot_size_step)
        qty = max(spec.lot_size_min, min(spec.lot_size_max, qty))
        result["lot_size"] = qty
        result["stop_distance_pips"] = stop_distance / spec.pip_size
        result["pip_value_usd"] = spec.pip_size
        return result

    # For forex, synthetic, commodity: lot-based sizing
    stop_distance_pips = stop_distance / spec.pip_size
    result["stop_distance_pips"] = round(stop_distance_pips, 1)

    pip_value = _get_pip_value_usd(
        spec,
        current_price=entry_price,
        usd_quote_rate=usd_quote_rate,
    )
    result["pip_value_usd"] = round(pip_value, 4)

    if pip_value <= 0 or stop_distance_pips <= 0:
        result["error"] = "Invalid pip value or stop distance"
        return result

    # lot_size = risk_amount / (stop_distance_pips * pip_value_per_lot)
    raw_lots = risk_amount / (stop_distance_pips * pip_value)
    lots = _round_to_step(raw_lots, spec.lot_size_step)
    lots = max(spec.lot_size_min, min(spec.lot_size_max, lots))
    result["lot_size"] = lots

    return result


def format_position_size_summary(sizing: dict, symbol: str) -> str:
    """Human-readable summary for logging and UI display."""
    if sizing.get("error"):
        return f"{symbol}: ERROR — {sizing['error']}"
    return (
        f"{symbol}: lot={sizing['lot_size']} "
        f"risk=${sizing['risk_amount_usd']:.2f} "
        f"stop_pips={sizing['stop_distance_pips']:.1f} "
        f"pip_val=${sizing['pip_value_usd']:.4f}"
    )
