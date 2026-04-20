"""
IKENGA Paper Trading Engine

Two responsibilities:
1. monitor_open_positions — check all open PaperTrades
   against latest prices, close if stop or TP hit,
   update PnL.
2. check_drawdown — for each account, compute current
   drawdown and pause if limit breached.
3. run_paper_engine — calls both in sequence.
   Called by the 4-hour refresh after market state update.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.cache.candle_store import get_candles
from src.db.models import PaperAccount, PaperTrade

logger = logging.getLogger(__name__)


def _is_long(trade: PaperTrade) -> bool:
    """Long/up vs short/down (signal bridge uses up/down)."""
    d = (trade.direction or "").lower()
    return d in ("long", "up")


def _get_latest_price(
    symbol: str,
    db: Session,
) -> Optional[float]:
    """
    Get the most recent close price for a symbol.
    Uses 4H candles as the reference — same as the
    active refresh cycle. Returns None if unavailable.
    """
    for tf in ["4h", "1h", "15m", "1d"]:
        try:
            candles = get_candles(symbol, tf, db)
            if candles:
                return float(candles[-1].close)
        except Exception:
            continue
    return None


def _calculate_pnl(
    trade: PaperTrade,
    close_price: float,
) -> tuple[float, float]:
    """
    Calculate PnL in USD and percentage for a closing trade.

    For CFD-style (non-crypto): uses lot_size and
    risk_amount_usd to estimate PnL proportionally.

    Formula:
    price_diff = close_price - entry_price (long)
               = entry_price - close_price (short)
    stop_distance = abs(entry_price - stop_price)
    pnl_usd = (price_diff / stop_distance) * risk_amount_usd

    This gives exact PnL relative to the risked amount.
    If trade hits stop exactly: pnl = -risk_amount_usd
    If trade hits TP: pnl = positive proportional amount

    Returns (pnl_usd, pnl_pct_of_account) where
    pnl_pct is relative to risk_amount_usd not account.
    """
    if _is_long(trade):
        price_diff = close_price - trade.entry_price
    else:
        price_diff = trade.entry_price - close_price

    stop_distance = abs(trade.entry_price - trade.stop_price)
    if stop_distance <= 0:
        return 0.0, 0.0

    pnl_usd = (price_diff / stop_distance) * trade.risk_amount_usd
    pnl_pct = (price_diff / trade.entry_price) * 100.0

    return round(pnl_usd, 2), round(pnl_pct, 4)


def _close_trade(
    trade: PaperTrade,
    close_price: float,
    status: str,
    db: Session,
) -> None:
    """
    Close a trade and update the account balance.
    status: "closed_tp" | "closed_sl" | "closed_time"
    """
    now = datetime.now(timezone.utc)
    pnl_usd, pnl_pct = _calculate_pnl(trade, close_price)

    trade.status = status
    trade.close_at = now
    trade.close_price = close_price
    trade.pnl_usd = pnl_usd
    trade.pnl_pct = pnl_pct

    # Update account balance
    account = db.query(PaperAccount).filter(
        PaperAccount.id == trade.account_id
    ).first()
    if account is not None:
        account.balance_usd = round(
            account.balance_usd + pnl_usd, 2
        )

    logger.info(
        "Paper trade closed: %s %s %s "
        "entry=%.5f close=%.5f pnl=$%.2f (%.4f%%)",
        trade.symbol, trade.direction, status,
        trade.entry_price, close_price,
        pnl_usd, pnl_pct,
    )


def monitor_open_positions(
    db: Session,
    universe: str | None = None,
) -> dict:
    """
    Check all open PaperTrades against latest prices.
    Close trades that have hit stop loss or take profit.
    Also close trades that have exceeded time_exit_days.

    When ``universe`` is provided, only trades whose
    symbol belongs to that universe are processed.

    Returns summary dict with counts.
    """
    open_trades = (
        db.query(PaperTrade)
        .filter(PaperTrade.status == "open")
        .all()
    )

    if universe is not None:
        from src.api.routers.setups import _infer_universe

        open_trades = [
            t for t in open_trades
            if _infer_universe(t.symbol) == universe
        ]

    if not open_trades:
        return {
            "checked": 0, "closed_tp": 0,
            "closed_sl": 0, "closed_time": 0,
        }

    counts = {"checked": 0, "closed_tp": 0,
              "closed_sl": 0, "closed_time": 0}

    # Get account settings for time exit
    account_map: dict[int, PaperAccount] = {}
    for trade in open_trades:
        if trade.account_id not in account_map:
            acct = db.query(PaperAccount).filter(
                PaperAccount.id == trade.account_id
            ).first()
            if acct:
                account_map[trade.account_id] = acct

    now = datetime.now(timezone.utc)

    for trade in open_trades:
        counts["checked"] += 1

        # Check time-based exit first
        account = account_map.get(trade.account_id)
        if account and account.time_exit_days is not None:
            open_at = trade.open_at
            if open_at.tzinfo is None:
                open_at = open_at.replace(tzinfo=timezone.utc)
            days_open = (now - open_at).days
            if days_open >= account.time_exit_days:
                latest = _get_latest_price(trade.symbol, db)
                if latest is not None:
                    _close_trade(
                        trade, latest, "closed_time", db
                    )
                    counts["closed_time"] += 1
                    continue

        # Get latest price
        latest = _get_latest_price(trade.symbol, db)
        if latest is None:
            logger.debug(
                "%s: cannot get latest price, skipping",
                trade.symbol
            )
            continue

        # Check stop loss
        stop_hit = False
        if _is_long(trade):
            stop_hit = latest <= trade.stop_price
        else:
            stop_hit = latest >= trade.stop_price

        if stop_hit:
            _close_trade(
                trade, trade.stop_price, "closed_sl", db
            )
            counts["closed_sl"] += 1
            continue

        # Check take profit (only if TP is set)
        if trade.take_profit_price is not None:
            tp_hit = False
            if _is_long(trade):
                tp_hit = latest >= trade.take_profit_price
            else:
                tp_hit = latest <= trade.take_profit_price

            if tp_hit:
                _close_trade(
                    trade, trade.take_profit_price,
                    "closed_tp", db
                )
                counts["closed_tp"] += 1
                continue

    return counts


def check_drawdown(db: Session) -> list[str]:
    """
    For each active paper account, compute current drawdown.
    If drawdown exceeds limit, set is_paused_drawdown=True.
    If previously paused and drawdown recovered, unpause.

    Drawdown = (initial_balance - current_balance)
               / initial_balance * 100

    Returns list of account names that were paused.
    """
    accounts = db.query(PaperAccount).filter(
        PaperAccount.is_active.is_(True)
    ).all()

    paused = []

    for account in accounts:
        if account.initial_balance_usd <= 0:
            continue

        drawdown_pct = (
            (account.initial_balance_usd - account.balance_usd)
            / account.initial_balance_usd * 100.0
        )

        if drawdown_pct >= account.drawdown_limit_pct:
            if not account.is_paused_drawdown:
                account.is_paused_drawdown = True
                paused.append(account.name)
                logger.warning(
                    "Paper account '%s' paused: "
                    "drawdown %.1f%% >= limit %.1f%%",
                    account.name, drawdown_pct,
                    account.drawdown_limit_pct,
                )
        else:
            # Recover from pause if drawdown improved
            if account.is_paused_drawdown:
                account.is_paused_drawdown = False
                logger.info(
                    "Paper account '%s' unpaused: "
                    "drawdown %.1f%% < limit %.1f%%",
                    account.name, drawdown_pct,
                    account.drawdown_limit_pct,
                )

    return paused


def run_paper_engine(
    db: Session,
    universe: str | None = None,
) -> dict:
    """
    Main entry point called by the 4-hour refresh.
    Order:
    1. Monitor open positions (close stops/TPs)
    2. Check drawdown (pause breached accounts)
    3. Check entry signals (open new trades)

    When ``universe`` is provided, monitor / entry checks
    are restricted to symbols in that universe.

    Returns summary of all actions taken.
    """
    from src.execution.signal_bridge import check_entry_signals

    # Step 1 — monitor positions (universe-scoped)
    monitor_result = monitor_open_positions(
        db, universe=universe
    )

    # Step 2 — check drawdown (always all accounts)
    paused_accounts = check_drawdown(db)

    # Commit position and drawdown changes before
    # checking new signals
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Paper engine commit failed: %s", e)
        return {
            "error": str(e),
            "monitor": monitor_result,
            "universe": universe or "all",
        }

    # Step 3 — check for new entries (universe-scoped)
    try:
        new_trades = check_entry_signals(
            db, universe=universe
        )
    except Exception as e:
        logger.error("Signal check failed: %s", e)
        new_trades = []

    return {
        "monitor": monitor_result,
        "paused_accounts": paused_accounts,
        "new_trades_opened": len(new_trades),
        "new_trades": new_trades,
        "universe": universe or "all",
    }
