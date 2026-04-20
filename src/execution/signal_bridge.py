"""
IKENGA Signal Bridge — State Machine + EMA Entry

Monitors top-50 setups for paper trading entry conditions:
1. Market state >= configured minimum (default CANDIDATE_ACTIVE)
2. EMA fast/slow crossover on configured timeframe (default 15m)
3. No existing open position for symbol on this account
4. Candidate impulse start price available for stop placement

When conditions met, creates a PaperTrade record.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session

from src.cache.candle_store import get_candles
from src.db.models import MonitoredSetup, PaperAccount, PaperTrade
from src.execution.account_router import get_account_type_for_symbol
from src.execution.position_sizing import calculate_lot_size
from src.scanner.global_structure import (
    get_stored_candidate_impulse,
    get_stored_global_structure,
)

logger = logging.getLogger(__name__)

# Market state ordering — higher index = more advanced state
MARKET_STATE_ORDER = [
    "WAITING",
    "RETRACEMENT",
    "DEPTH_BUILDING",
    "CHOCH_ZONE_ACTIVE",
    "CHOCH_TESTED",
    "CANDIDATE_ACTIVE",
    "CANDIDATE_CHOCH_TESTED",
    "ENTRY_ZONE",
    "CANDIDATE_CONFIRMED",
    "STRUCTURE_BROKEN",
]


def _state_rank(state: str) -> int:
    try:
        return MARKET_STATE_ORDER.index(state)
    except ValueError:
        return 0


def _state_meets_minimum(state: str, minimum: str) -> bool:
    return _state_rank(state) >= _state_rank(minimum)


def _compute_ema(prices: list[float], period: int) -> list[float]:
    """Compute EMA for a list of prices. Returns same length list."""
    if len(prices) < period:
        return [float("nan")] * len(prices)
    k = 2.0 / (period + 1)
    ema = [float("nan")] * len(prices)
    # Seed with SMA of first `period` values
    ema[period - 1] = sum(prices[:period]) / period
    for i in range(period, len(prices)):
        ema[i] = prices[i] * k + ema[i - 1] * (1 - k)
    return ema


def _detect_ema_crossover(
    candles: list[Any],
    fast_period: int,
    slow_period: int,
    direction: str,
) -> Optional[float]:
    """
    Check if EMA fast crossed EMA slow on the most recent
    completed candle in the correct direction.

    direction: "up" checks for fast crossing above slow (long)
               "down" checks for fast crossing below slow (short)

    Returns the close price of the crossover candle if crossover
    detected on the last candle, else None.

    Crossover is confirmed when:
    - On candle[-2]: fast was on the wrong side of slow
    - On candle[-1]: fast is now on the correct side of slow
    """
    if len(candles) < slow_period + 2:
        return None

    closes = [float(c.close) for c in candles]
    fast = _compute_ema(closes, fast_period)
    slow = _compute_ema(closes, slow_period)

    # Last two valid values
    n = len(closes)
    f1, s1 = fast[n - 2], slow[n - 2]  # previous candle
    f0, s0 = fast[n - 1], slow[n - 1]  # current/last candle

    if any(v != v for v in [f1, s1, f0, s0]):
        # NaN check
        return None

    if direction == "up":
        # Bullish crossover: fast was below slow, now above
        if f1 < s1 and f0 > s0:
            return closes[-1]
    elif direction == "down":
        # Bearish crossover: fast was above slow, now below
        if f1 > s1 and f0 < s0:
            return closes[-1]

    return None


def _get_stop_price(
    candidate_cache: Any,
    direction: str,
    candles: list[Any],
    buffer_pct: float = 0.001,
) -> Optional[float]:
    """
    Stop loss = just beyond the start of the candidate impulse.

    For long: stop = candidate_start_low * (1 - buffer_pct)
    For short: stop = candidate_start_high * (1 + buffer_pct)

    Uses candidate_cache.start_timestamp to find the candle.
    """
    if candidate_cache is None:
        return None

    start_ts = candidate_cache.start_timestamp
    if start_ts is None:
        return None

    if start_ts.tzinfo is None:
        start_ts = start_ts.replace(tzinfo=timezone.utc)

    # Find nearest candle to candidate start
    best = None
    best_diff = float("inf")
    for c in candles:
        cts = c.timestamp
        if cts.tzinfo is None:
            cts = cts.replace(tzinfo=timezone.utc)
        diff = abs((cts - start_ts).total_seconds())
        if diff < best_diff:
            best_diff = diff
            best = c

    if best is None:
        return None

    if direction == "up":
        return float(best.low) * (1 - buffer_pct)
    else:
        return float(best.high) * (1 + buffer_pct)


def _get_take_profit_price(
    gsc: Any,
    direction: str,
    tp_mode: str = "global_bos",
) -> Optional[float]:
    """
    Take profit based on tp_mode.
    Currently implements global_bos only.
    Returns the global BOS price from GlobalStructureCache.
    """
    if tp_mode != "global_bos" or gsc is None:
        return None

    bos_levels = gsc.bos_levels_json or []
    if not bos_levels:
        return None

    # Find the most recent confirmed BOS in trend direction
    confirmed = [
        b for b in bos_levels
        if b.get("confirmed") and not b.get("broken")
    ]
    if not confirmed:
        return None

    # For uptrend: TP = highest confirmed BOS price
    # For downtrend: TP = lowest confirmed BOS price
    prices = [float(b.get("price", 0)) for b in confirmed
              if b.get("price")]
    if not prices:
        return None

    if direction == "up":
        return max(prices)
    else:
        return min(prices)


def _has_open_position(
    symbol: str,
    account_id: int,
    db: Session,
) -> bool:
    return (
        db.query(PaperTrade)
        .filter(
            PaperTrade.symbol == symbol,
            PaperTrade.account_id == account_id,
            PaperTrade.status == "open",
        )
        .first()
    ) is not None


def _get_account(
    account_type: str,
    symbol: str,
    db: Session,
) -> Optional[PaperAccount]:
    from src.api.routers.setups import _infer_universe

    symbol_universe = _infer_universe(symbol)
    return (
        db.query(PaperAccount)
        .filter(
            PaperAccount.account_type == account_type,
            PaperAccount.is_active.is_(True),
            PaperAccount.is_paused_drawdown.is_(False),
            sa.or_(
                PaperAccount.universe == symbol_universe,
                PaperAccount.universe.is_(None),
            ),
        )
        .first()
    )


def _count_open_positions(account_id: int, db: Session) -> int:
    return (
        db.query(PaperTrade)
        .filter(
            PaperTrade.account_id == account_id,
            PaperTrade.status == "open",
        )
        .count()
    )


def check_entry_signals(
    db: Session,
    universe: str | None = None,
) -> list[dict]:
    """
    Main entry point. Called by the 4-hour refresh.
    Checks all monitored setups for entry conditions.
    When ``universe`` is provided, only setups belonging to
    that universe are considered.
    Returns list of trade dicts that were opened.
    """
    from src.api.routers.setups import _infer_universe

    opened_trades = []

    setups = db.query(MonitoredSetup).all()
    if universe is not None:
        setups = [
            s for s in setups
            if _infer_universe(s.symbol) == universe
        ]

    for setup in setups:
        symbol = setup.symbol
        market_state = setup.market_state or "WAITING"
        trend = setup.htf_trend_direction or "range"

        if trend == "range":
            continue

        # Get account for this symbol
        account_type = get_account_type_for_symbol(symbol)
        symbol_universe = _infer_universe(symbol)

        # Skip symbols whose universe is not handled by any
        # active account (universe-aware short-circuit).
        universe_account = (
            db.query(PaperAccount)
            .filter(
                PaperAccount.is_active.is_(True),
                PaperAccount.is_paused_drawdown.is_(False),
                sa.or_(
                    PaperAccount.universe == symbol_universe,
                    PaperAccount.universe.is_(None),
                ),
            )
            .first()
        )
        if universe_account is None:
            continue

        account = _get_account(account_type, symbol, db)
        if account is None:
            continue

        # Check state minimum
        if not _state_meets_minimum(
            market_state, account.min_market_state
        ):
            continue

        # Check concurrent position limit
        open_count = _count_open_positions(account.id, db)
        if open_count >= account.max_concurrent_positions:
            continue

        # Check no existing position for this symbol
        if _has_open_position(symbol, account.id, db):
            continue

        # Determine direction
        direction = "up" if trend == "up" else "down"

        # Fetch entry timeframe candles
        try:
            entry_candles = get_candles(
                symbol, account.entry_timeframe, db
            )
        except Exception as e:
            logger.debug(
                "Cannot fetch %s candles for %s: %s",
                account.entry_timeframe, symbol, e
            )
            continue

        if len(entry_candles) < account.entry_ema_slow + 5:
            continue

        # Check EMA crossover
        entry_price = _detect_ema_crossover(
            entry_candles,
            fast_period=account.entry_ema_fast,
            slow_period=account.entry_ema_slow,
            direction=direction,
        )

        if entry_price is None:
            continue

        # Get candidate impulse for stop placement
        candidate = get_stored_candidate_impulse(symbol, db)

        # Get reference candles for stop calculation
        # Use 4H candles as the reference for stop candle
        try:
            ref_candles = get_candles(symbol, "4h", db)
        except Exception:
            ref_candles = entry_candles

        stop_price = _get_stop_price(
            candidate, direction, ref_candles
        )

        if stop_price is None:
            logger.debug(
                "%s: cannot determine stop price, skipping",
                symbol
            )
            continue

        # Validate stop makes sense vs entry
        if direction == "up" and stop_price >= entry_price:
            continue
        if direction == "down" and stop_price <= entry_price:
            continue

        # Get take profit
        gsc = get_stored_global_structure(symbol, db)
        tp_price = _get_take_profit_price(
            gsc, direction, account.tp_mode
        )

        # Calculate position size
        sizing = calculate_lot_size(
            symbol=symbol,
            account_balance_usd=account.balance_usd,
            risk_pct=account.risk_per_trade_pct,
            entry_price=entry_price,
            stop_price=stop_price,
            db=db,
        )

        if sizing.get("error") or sizing["lot_size"] <= 0:
            logger.debug(
                "%s: position sizing failed: %s",
                symbol, sizing.get("error")
            )
            continue

        # Create paper trade
        trade = PaperTrade(
            account_id=account.id,
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            stop_price=stop_price,
            take_profit_price=tp_price,
            lot_size=sizing["lot_size"],
            risk_amount_usd=sizing["risk_amount_usd"],
            market_state_at_entry=market_state,
            score_at_entry=float(setup.trend_score or 0),
            entry_timeframe=account.entry_timeframe,
            status="open",
            open_at=datetime.now(timezone.utc),
        )
        db.add(trade)

        logger.info(
            "Paper trade opened: %s %s entry=%.5f "
            "stop=%.5f tp=%s lot=%.3f risk=$%.2f",
            symbol, direction, entry_price, stop_price,
            f"{tp_price:.5f}" if tp_price else "None",
            sizing["lot_size"], sizing["risk_amount_usd"],
        )

        opened_trades.append({
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "take_profit_price": tp_price,
            "lot_size": sizing["lot_size"],
            "risk_amount_usd": sizing["risk_amount_usd"],
            "market_state": market_state,
            "account": account.name,
        })

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Failed to commit paper trades: %s", e)
        return []

    return opened_trades


# -------------------------------------------------------
# LEGACY functions — kept so existing imports do not break
# Not used by paper trading engine
# -------------------------------------------------------
from src.core.filter_defaults import SCAN_AND_ANALYSIS_FILTER_DEFAULTS
from src.core.signals import Signal
from src.core.trend_id import identify_trend
from src.execution.contracts import NormalizedOrderIntent, ProviderId


def trend_snapshot_to_signal(
    candles: list[Any],
    filter_kw: dict[str, Any] | None = None,
) -> Signal:
    kw = dict(SCAN_AND_ANALYSIS_FILTER_DEFAULTS)
    if filter_kw:
        kw.update(filter_kw)
    result = identify_trend(candles, **kw)
    trend = (result.get("trend") or "range").lower()
    phase = (result.get("current_phase") or "range").lower()
    last_close = float(candles[-1].close) if candles else 0.0
    if phase == "impulse" and trend == "up":
        return Signal(status="open", direction="long",
                      entry_price=last_close, size=1.0,
                      metadata={"source": "legacy"})
    if phase == "impulse" and trend == "down":
        return Signal(status="open", direction="short",
                      entry_price=last_close, size=1.0,
                      metadata={"source": "legacy"})
    return Signal(status="no_trade",
                  metadata={"source": "legacy"})


def signal_to_intent(
    signal: Signal,
    *,
    symbol: str,
    stake_amount: float = 10.0,
    provider: ProviderId = ProviderId.DERIV,
    duration: int = 5,
    duration_unit: str = "t",
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
        metadata={},
    )
