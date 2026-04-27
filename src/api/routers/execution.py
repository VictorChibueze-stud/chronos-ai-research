from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime as dt
from typing import Optional

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.cache import candle_store
from src.db.models import ContractSpec, ExecutionOrder, PaperAccount, PaperTrade
from src.db.session import get_db
from src.execution.contracts import NormalizedOrderIntent, OrderSubmissionResponse
from src.execution.env_config import execution_enabled, execution_paper_only, execution_provider
from src.execution.orchestrator import ExecutionOrchestrator
from src.execution.paper_engine import (
    check_drawdown,
    monitor_open_positions,
    run_paper_engine,
)
from src.execution.position_sizing import (
    calculate_lot_size,
    format_position_size_summary,
)
from src.execution.signal_bridge import (
    check_entry_signals,
    signal_to_intent,
    trend_snapshot_to_signal,
)

router = APIRouter(prefix="/api/execution", tags=["execution"])


class FromSignalRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    timeframe: str = Field("1h", min_length=1)
    stake_amount: float = Field(10.0, gt=0)


@router.get("/status")
def get_execution_status() -> dict[str, bool | str]:
    return {
        "execution_enabled": execution_enabled(),
        "execution_paper_only": execution_paper_only(),
        "execution_provider": execution_provider(),
    }


@router.post("/orders", response_model=OrderSubmissionResponse)
def post_execution_order(
    body: NormalizedOrderIntent,
    db: Session = Depends(get_db),
) -> OrderSubmissionResponse:
    orch = ExecutionOrchestrator(db)
    return orch.submit(body)


@router.post("/from-signal", response_model=OrderSubmissionResponse)
def post_execution_from_signal(
    body: FromSignalRequest,
    db: Session = Depends(get_db),
) -> OrderSubmissionResponse:
    try:
        candles = candle_store.get_candles(body.symbol.upper(), body.timeframe.lower(), db)
    except candle_store.CandleDataError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"reason": exc.reason, "message": str(exc)},
        ) from exc
    if not candles:
        raise HTTPException(status_code=422, detail="No candles for symbol/timeframe")
    signal = trend_snapshot_to_signal(candles)
    intent = signal_to_intent(signal, symbol=body.symbol, stake_amount=body.stake_amount)
    if intent is None:
        raise HTTPException(
            status_code=422,
            detail={"message": "No actionable signal (need impulse phase with directional trend).", "signal": signal.status},
        )
    orch = ExecutionOrchestrator(db)
    return orch.submit(intent)


@router.get("/orders")
def list_execution_orders(
    limit: int = 50,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return {"items": ExecutionOrchestrator(db).list_orders(limit=limit)}


@router.get("/orders/{order_id}/events")
def list_order_events(
    order_id: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    order = db.query(ExecutionOrder).filter(ExecutionOrder.id == order_id).one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    rows = ExecutionOrchestrator(db).list_events(order_id)
    return {"order_id": order_id, "items": rows}


@router.get("/contract-specs")
def list_contract_specs(
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = (
        db.query(ContractSpec)
        .order_by(
            ContractSpec.asset_class,
            ContractSpec.symbol,
        )
        .all()
    )
    return [
        {
            "symbol": r.symbol,
            "asset_class": r.asset_class,
            "pip_size": r.pip_size,
            "point_value": r.point_value,
            "contract_size": r.contract_size,
            "lot_size_min": r.lot_size_min,
            "lot_size_max": r.lot_size_max,
            "lot_size_step": r.lot_size_step,
            "quote_currency": r.quote_currency,
            "base_currency": r.base_currency,
            "is_crypto": r.is_crypto,
            "notes": r.notes,
            "last_fetched_at": r.last_fetched_at.isoformat()
            if r.last_fetched_at
            else None,
        }
        for r in rows
    ]


@router.post("/contract-specs/seed")
def seed_specs(db: Session = Depends(get_db)) -> dict:
    """Re-seed contract specs from built-in seed data."""
    from src.execution.seed_contract_specs import seed_contract_specs

    seed_contract_specs()
    count = db.query(ContractSpec).count()
    return {"status": "seeded", "total": count}


@router.post("/position-size/calculate")
def calculate_size(
    payload: dict,
    db: Session = Depends(get_db),
) -> dict:
    """
    Calculate lot size for a proposed trade.
    Body: {
        symbol, account_balance_usd, risk_pct,
        entry_price, stop_price,
        usd_quote_rate (optional)
    }
    """
    uqr = payload.get("usd_quote_rate")
    uqr_f = float(uqr) if uqr is not None else None
    result = calculate_lot_size(
        symbol=payload["symbol"],
        account_balance_usd=float(payload["account_balance_usd"]),
        risk_pct=float(payload["risk_pct"]),
        entry_price=float(payload["entry_price"]),
        stop_price=float(payload["stop_price"]),
        db=db,
        usd_quote_rate=uqr_f,
    )
    result["summary"] = format_position_size_summary(
        result, payload["symbol"]
    )
    return result


@router.get("/paper/accounts")
def list_paper_accounts(
    db: Session = Depends(get_db),
) -> list[dict]:
    accounts = db.query(PaperAccount).all()
    result = []
    for a in accounts:
        open_trades = (
            db.query(PaperTrade)
            .filter(
                PaperTrade.account_id == a.id,
                PaperTrade.status == "open",
            )
            .count()
        )
        closed = (
            db.query(PaperTrade)
            .filter(
                PaperTrade.account_id == a.id,
                PaperTrade.status != "open",
                PaperTrade.pnl_usd.isnot(None),
            )
            .all()
        )
        total_pnl = sum(t.pnl_usd or 0 for t in closed)
        wins = sum(1 for t in closed if (t.pnl_usd or 0) > 0)
        win_rate = (wins / len(closed) * 100) if closed else 0
        result.append({
            "id": a.id,
            "name": a.name,
            "account_type": a.account_type,
            "balance_usd": a.balance_usd,
            "initial_balance_usd": a.initial_balance_usd,
            "total_pnl_usd": round(total_pnl, 2),
            "total_pnl_pct": round(
                total_pnl / a.initial_balance_usd * 100, 2
            ),
            "open_positions": open_trades,
            "total_closed_trades": len(closed),
            "win_rate_pct": round(win_rate, 1),
            "drawdown_limit_pct": a.drawdown_limit_pct,
            "risk_per_trade_pct": a.risk_per_trade_pct,
            "max_concurrent_positions": a.max_concurrent_positions,
            "scale_by_score": a.scale_by_score,
            "entry_ema_fast": a.entry_ema_fast,
            "entry_ema_slow": a.entry_ema_slow,
            "entry_timeframe": a.entry_timeframe,
            "min_market_state": a.min_market_state,
            "tp_mode": a.tp_mode,
            "entry_lookback_candles": a.entry_lookback_candles,
            "entry_check_interval_hours": a.entry_check_interval_hours,
            "time_exit_days": a.time_exit_days,
            "is_active": a.is_active,
            "is_paused_drawdown": a.is_paused_drawdown,
            "universe": a.universe,
        })
    return result


@router.patch("/paper/accounts/{account_id}/settings")
def update_paper_account_settings(
    account_id: int,
    payload: dict,
    db: Session = Depends(get_db),
) -> dict:
    account = db.query(PaperAccount).filter(
        PaperAccount.id == account_id
    ).first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    allowed = {
        "drawdown_limit_pct", "risk_per_trade_pct",
        "max_concurrent_positions", "scale_by_score",
        "entry_ema_fast", "entry_ema_slow",
        "entry_timeframe", "min_market_state",
        "tp_mode",
        "entry_lookback_candles",
        "entry_check_interval_hours",
        "time_exit_days",
        "is_active", "is_paused_drawdown",
    }
    for key, value in payload.items():
        if key in allowed:
            setattr(account, key, value)
    db.commit()
    return {"status": "updated", "account_id": account_id}


_ALLOWED_METRIC_TARGETS = {
    "sharpe_target",
    "sortino_target",
    "calmar_target",
    "profit_factor_target",
    "max_dd_pct_target",
    "win_rate_target",
    "risk_reward_target",
}


def _load_metric_targets(account: PaperAccount) -> dict:
    import json

    raw = getattr(account, "metric_targets_json", None) or ""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        k: float(v)
        for k, v in data.items()
        if k in _ALLOWED_METRIC_TARGETS and isinstance(v, (int, float))
    }


@router.patch("/paper/accounts/{account_id}/targets")
def update_account_targets(
    account_id: int,
    payload: dict,
    db: Session = Depends(get_db),
) -> dict:
    """
    Store performance metric targets for an account.
    These are display-only targets for the Risk page —
    they do not affect trading logic.
    """
    import json

    account = db.query(PaperAccount).filter(
        PaperAccount.id == account_id
    ).first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    incoming = {
        k: float(v)
        for k, v in payload.items()
        if k in _ALLOWED_METRIC_TARGETS
    }
    existing = _load_metric_targets(account)
    existing.update(incoming)
    account.metric_targets_json = json.dumps(existing)
    db.commit()
    return {"status": "saved", "targets": existing}


@router.get("/paper/accounts/{account_id}/targets")
def get_account_targets(
    account_id: int,
    db: Session = Depends(get_db),
) -> dict:
    account = db.query(PaperAccount).filter(
        PaperAccount.id == account_id
    ).first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return _load_metric_targets(account)


@router.get("/paper/trades")
def list_paper_trades(
    account_id: Optional[int] = None,
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[dict]:
    q = db.query(PaperTrade)
    if account_id is not None:
        q = q.filter(PaperTrade.account_id == account_id)
    if symbol:
        q = q.filter(
            PaperTrade.symbol == symbol.strip().upper()
        )
    if status:
        q = q.filter(PaperTrade.status == status)
    trades = q.order_by(
        PaperTrade.open_at.desc()
    ).limit(max(1, min(limit, 500))).all()
    return [
        {
            "id": t.id,
            "account_id": t.account_id,
            "symbol": t.symbol,
            "direction": t.direction,
            "entry_price": t.entry_price,
            "stop_price": t.stop_price,
            "take_profit_price": t.take_profit_price,
            "lot_size": t.lot_size,
            "risk_amount_usd": t.risk_amount_usd,
            "market_state_at_entry": t.market_state_at_entry,
            "score_at_entry": t.score_at_entry,
            "entry_timeframe": t.entry_timeframe,
            "status": t.status,
            "open_at": t.open_at.isoformat(),
            "close_at": t.close_at.isoformat()
            if t.close_at else None,
            "close_price": t.close_price,
            "pnl_usd": t.pnl_usd,
            "pnl_pct": t.pnl_pct,
        }
        for t in trades
    ]


@router.post("/paper/signals/check")
def manual_check_signals(
    db: Session = Depends(get_db),
) -> dict:
    """Manually trigger signal check for testing."""
    opened = check_entry_signals(db)
    return {
        "status": "checked",
        "trades_opened": len(opened),
        "trades": opened,
    }


@router.get("/paper/performance")
def get_paper_performance(
    account_id: Optional[int] = None,
    universe: Optional[str] = None,
    db: Session = Depends(get_db),
) -> dict:
    """
    Aggregate performance stats across all accounts
    or for a specific account.
    Returns PnL curve data points, win rate, avg RR,
    max drawdown, and current open exposure.

    When ``universe`` is set, results are filtered to
    trades whose symbol belongs to that universe.
    """
    universe_symbols: set[str] | None = None
    if universe is not None:
        from src.api.routers.setups import _infer_universe

        all_trade_symbols = [
            row[0]
            for row in db.query(PaperTrade.symbol).distinct().all()
        ]
        universe_symbols = {
            s for s in all_trade_symbols
            if _infer_universe(s) == universe
        }

    q = db.query(PaperTrade).filter(
        PaperTrade.status != "open",
        PaperTrade.pnl_usd.isnot(None),
    )
    if account_id is not None:
        q = q.filter(PaperTrade.account_id == account_id)
    if universe_symbols is not None:
        if not universe_symbols:
            q = q.filter(sa.false())
        else:
            q = q.filter(PaperTrade.symbol.in_(universe_symbols))
    closed = q.order_by(PaperTrade.close_at.asc()).all()

    open_q = db.query(PaperTrade).filter(
        PaperTrade.status == "open"
    )
    if account_id is not None:
        open_q = open_q.filter(
            PaperTrade.account_id == account_id
        )
    if universe_symbols is not None:
        if not universe_symbols:
            open_q = open_q.filter(sa.false())
        else:
            open_q = open_q.filter(
                PaperTrade.symbol.in_(universe_symbols)
            )
    open_trades = open_q.all()

    total_pnl = sum(t.pnl_usd or 0 for t in closed)
    wins = [t for t in closed if (t.pnl_usd or 0) > 0]
    losses = [t for t in closed if (t.pnl_usd or 0) <= 0]
    win_rate = len(wins) / len(closed) * 100 if closed else 0

    avg_win = (
        sum((t.pnl_usd or 0) for t in wins) / len(wins)
        if wins else 0
    )
    avg_loss = (
        sum(abs(t.pnl_usd or 0) for t in losses) / len(losses)
        if losses else 0
    )
    risk_reward = (
        avg_win / avg_loss if avg_loss > 0 else 0
    )

    # PnL curve — cumulative PnL over time
    curve = []
    cumulative = 0.0
    for t in closed:
        cumulative += t.pnl_usd or 0
        curve.append({
            "timestamp": t.close_at.isoformat()
            if t.close_at else None,
            "cumulative_pnl": round(cumulative, 2),
            "trade_pnl": t.pnl_usd,
            "symbol": t.symbol,
        })

    # Max drawdown from curve
    peak = 0.0
    max_dd = 0.0
    for point in curve:
        cp = point["cumulative_pnl"]
        if cp > peak:
            peak = cp
        dd = peak - cp
        if dd > max_dd:
            max_dd = dd

    # Open exposure
    open_exposure = sum(t.risk_amount_usd for t in open_trades)

    # --- Risk-adjusted performance metrics ---
    # Group closed-trade PnL by calendar date so daily returns
    # are independent of how many trades closed that day.
    daily_pnl: dict[str, float] = defaultdict(float)
    for t in closed:
        if t.close_at:
            day_key = t.close_at.strftime("%Y-%m-%d")
            daily_pnl[day_key] += (t.pnl_usd or 0)
    daily_returns = list(daily_pnl.values())

    # Sharpe — annualized with sqrt(252), risk-free = 0.
    sharpe_ratio = 0.0
    if len(daily_returns) >= 2:
        mean_r = sum(daily_returns) / len(daily_returns)
        variance = sum(
            (r - mean_r) ** 2 for r in daily_returns
        ) / (len(daily_returns) - 1)
        std_r = math.sqrt(variance) if variance > 0 else 0.0
        if std_r > 0:
            sharpe_ratio = round(
                (mean_r / std_r) * math.sqrt(252), 2
            )

    # Sortino — penalizes only negative daily returns.
    sortino_ratio = 0.0
    downside_returns = [r for r in daily_returns if r < 0]
    if len(downside_returns) >= 2 and daily_returns:
        mean_r = sum(daily_returns) / len(daily_returns)
        downside_var = (
            sum(r ** 2 for r in downside_returns)
            / len(downside_returns)
        )
        downside_std = math.sqrt(downside_var)
        if downside_std > 0:
            sortino_ratio = round(
                (mean_r / downside_std) * math.sqrt(252), 2
            )

    # Calmar — annualized return / max drawdown ($).
    calmar_ratio = 0.0
    if max_dd > 0 and closed:
        opens = [t.open_at for t in closed if t.open_at]
        closes = [t.close_at for t in closed if t.close_at]
        if opens and closes:
            first_date = min(opens)
            last_date = max(closes)
            years = max(
                (last_date - first_date).days / 365.25, 0.01
            )
            annualized_return = total_pnl / years
            calmar_ratio = round(annualized_return / max_dd, 2)

    # Max drawdown as % of initial balance. Falls back to a
    # 100k notional when no specific account is requested.
    initial_balance = 100000.0
    if account_id is not None:
        acct = (
            db.query(PaperAccount)
            .filter(PaperAccount.id == account_id)
            .first()
        )
        if acct:
            initial_balance = acct.initial_balance_usd
    max_dd_pct = (
        round((max_dd / initial_balance * 100), 2)
        if initial_balance > 0 else 0.0
    )

    # Max drawdown duration — days currently spent below the
    # running equity peak. Walk the curve looking for the start
    # of the most recent under-peak run.
    max_dd_duration_days = 0
    current_dd_start: str | None = None
    peak_for_duration = 0.0
    for point in curve:
        cp = point["cumulative_pnl"]
        if cp >= peak_for_duration:
            peak_for_duration = cp
            current_dd_start = None
        else:
            if current_dd_start is None and point["timestamp"]:
                current_dd_start = point["timestamp"]
    if current_dd_start and curve:
        try:
            start_dt = dt.fromisoformat(
                current_dd_start.replace("Z", "+00:00")
            )
            end_iso = (
                curve[-1]["timestamp"] or current_dd_start
            )
            end_dt = dt.fromisoformat(
                end_iso.replace("Z", "+00:00")
            )
            max_dd_duration_days = (end_dt - start_dt).days
        except (ValueError, AttributeError):
            max_dd_duration_days = 0

    # Profit factor — gross wins / gross losses.
    gross_wins = sum(t.pnl_usd or 0 for t in wins)
    gross_losses = sum(abs(t.pnl_usd or 0) for t in losses)
    profit_factor = (
        round(gross_wins / gross_losses, 2)
        if gross_losses > 0 else 0.0
    )

    return {
        "total_closed_trades": len(closed),
        "open_trades": len(open_trades),
        "total_pnl_usd": round(total_pnl, 2),
        "win_rate_pct": round(win_rate, 1),
        "avg_win_usd": round(avg_win, 2),
        "avg_loss_usd": round(avg_loss, 2),
        "risk_reward_ratio": round(risk_reward, 2),
        "max_drawdown_usd": round(max_dd, 2),
        "open_exposure_usd": round(open_exposure, 2),
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "calmar_ratio": calmar_ratio,
        "max_drawdown_pct": max_dd_pct,
        "max_drawdown_duration_days": max_dd_duration_days,
        "profit_factor": profit_factor,
        "pnl_curve": curve,
    }


@router.post("/paper/engine/run")
def manual_run_engine(
    db: Session = Depends(get_db),
) -> dict:
    """Manually trigger the full paper engine cycle."""
    result = run_paper_engine(db)
    return result


@router.post("/paper/trades/{trade_id}/close")
def manual_close_trade(
    trade_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """Manually close an open paper trade at current price."""
    from src.execution.paper_engine import _close_trade, _get_latest_price

    trade = db.query(PaperTrade).filter(
        PaperTrade.id == trade_id
    ).first()
    if trade is None:
        raise HTTPException(
            status_code=404, detail="Trade not found"
        )
    if trade.status != "open":
        raise HTTPException(
            status_code=400,
            detail=f"Trade is already {trade.status}"
        )
    latest = _get_latest_price(trade.symbol, db)
    if latest is None:
        raise HTTPException(
            status_code=503,
            detail="Cannot get current price"
        )
    _close_trade(trade, latest, "closed_manual", db)
    db.commit()
    return {
        "status": "closed",
        "trade_id": trade_id,
        "close_price": latest,
        "pnl_usd": trade.pnl_usd,
    }
