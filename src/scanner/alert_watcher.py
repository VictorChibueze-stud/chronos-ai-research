from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.adapters.binance_data import fetch_binance_ohlc_sync
from src.adapters.deriv_data import fetch_deriv_ohlc_sync
from src.adapters.yfinance_data import fetch_yfinance_ohlc_sync, is_yfinance_symbol
from src.core.structural_walker import serialize_state_report, walk_structure
from src.core.trend_id import identify_trend
from src.db.models import AlertZone, MonitoredSetup
from src.db.session import SessionLocal

logger = logging.getLogger(__name__)

_FILTER_CONFIG: dict[str, Any] = {
    "use_parent_relative_filter": True,
    "min_impulse_parent_ratio": 0.15,
    "use_momentum_filter": True,
    "min_momentum_ratio": 0.5,
    "use_dominance_filter": True,
    "min_dominance_ratio": 1.5,
}

_watcher_running = False
_watcher_task: asyncio.Task[None] | None = None


def _is_binance_symbol(symbol: str) -> bool:
    normalized = symbol.upper()
    return normalized.endswith("USDT") or normalized.endswith("BTC")


async def _fetch_candles(symbol: str, timeframe: str) -> list[Any]:
    normalized = symbol.upper()
    loop = asyncio.get_running_loop()

    if _is_binance_symbol(normalized):
        fetch_fn = lambda: fetch_binance_ohlc_sync(normalized, timeframe)
    elif is_yfinance_symbol(normalized):
        fetch_fn = lambda: fetch_yfinance_ohlc_sync(normalized, timeframe)
    else:
        fetch_fn = lambda: fetch_deriv_ohlc_sync(normalized, timeframe)

    candles = await loop.run_in_executor(None, fetch_fn)
    return list(candles)


def _extract_alert_zones_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    # Reuses the same level fields already consumed by setups serialization
    # (levels[].choch_zone and levels[].structural_level).
    extracted: list[dict[str, Any]] = []
    levels = state.get("levels", []) if isinstance(state, dict) else []
    global_trend = str(state.get("global_trend", "range")).lower() if isinstance(state, dict) else "range"

    for level in levels:
        depth = level.get("depth")

        choch = level.get("choch_zone")
        if isinstance(choch, dict):
            lower = choch.get("lower_boundary")
            upper = choch.get("upper_boundary")
            if lower is not None and upper is not None:
                low = float(min(lower, upper))
                high = float(max(lower, upper))
                extracted.append(
                    {
                        "zone_type": "DEPTH_CHOCH",
                        "depth": int(depth) if depth is not None else None,
                        "price_low": low,
                        "price_high": high,
                        "watch_condition": "price_enters_zone",
                    }
                )

        structural_level = level.get("structural_level")
        if isinstance(structural_level, dict):
            price = structural_level.get("price")
            if price is not None:
                watch_condition = "price_crosses_above"
                if global_trend == "down":
                    watch_condition = "price_crosses_below"
                p = float(price)
                extracted.append(
                    {
                        "zone_type": "DEPTH_BOS",
                        "depth": int(depth) if depth is not None else None,
                        "price_low": p,
                        "price_high": p,
                        "watch_condition": watch_condition,
                    }
                )

    return extracted


async def _trigger_reanalysis(setup: MonitoredSetup, db: Session) -> None:
    logger.warning("ALERT: %s — zone triggered, re-running analysis", setup.symbol)

    _current_state = setup.structural_state_json or {}
    _ = _current_state

    candles = await _fetch_candles(setup.symbol, setup.htf_timeframe)
    if not candles:
        return

    fresh_candles = candles[-200:]

    loop = asyncio.get_running_loop()
    trend_result = await loop.run_in_executor(
        None, lambda: identify_trend(fresh_candles, **_FILTER_CONFIG)
    )
    walker_result = await loop.run_in_executor(
        None,
        lambda: walk_structure(
            fresh_candles,
            trend_result,
            _FILTER_CONFIG,
            max_depth=3,
            symbol=setup.symbol,
        ),
    )
    serialized = await loop.run_in_executor(None, lambda: serialize_state_report(walker_result))

    setup.structural_state_json = serialized
    setup.last_checked_at = datetime.now(timezone.utc)
    setup.htf_trend_direction = trend_result.get("trend", setup.htf_trend_direction)
    setup.current_phase = trend_result.get("current_phase", setup.current_phase)
    max_depth = int(serialized.get("max_depth_reached", 0) or 0)
    mitigations = int(serialized.get("total_mitigation_count", 0) or 0)
    setup.trend_score = float((max_depth * 10) + (mitigations * 5))

    (
        db.query(AlertZone)
        .filter(AlertZone.setup_id == setup.id, AlertZone.is_manual_override.is_(False))
        .delete(synchronize_session=False)
    )

    for zone in _extract_alert_zones_from_state(serialized):
        db.add(
            AlertZone(
                setup_id=setup.id,
                zone_type=zone["zone_type"],
                depth=zone["depth"],
                price_high=zone["price_high"],
                price_low=zone["price_low"],
                is_active=True,
                watch_condition=zone["watch_condition"],
                is_manual_override=False,
            )
        )

    db.commit()


async def run_alert_watcher() -> None:
    global _watcher_running

    _watcher_running = True
    logger.warning("Alert watcher started")

    while _watcher_running:
        db = SessionLocal()
        try:
            active_zones = db.query(AlertZone).filter(AlertZone.is_active.is_(True)).all()
            grouped: dict[int, list[AlertZone]] = defaultdict(list)
            for zone in active_zones:
                grouped[zone.setup_id].append(zone)

            for setup_id, zones in grouped.items():
                setup = db.query(MonitoredSetup).filter(MonitoredSetup.id == setup_id).one_or_none()
                if setup is None:
                    continue

                try:
                    recent_candles = await _fetch_candles(setup.symbol, setup.htf_timeframe)
                except Exception:
                    continue

                if not recent_candles:
                    continue

                latest = recent_candles[-3:]
                if not latest:
                    continue

                live_price = float(latest[-1].close)
                fired_zone_ids: list[int] = []

                for zone in zones:
                    if zone.watch_condition == "price_enters_zone":
                        if float(zone.price_low) <= live_price <= float(zone.price_high):
                            fired_zone_ids.append(zone.id)
                    elif zone.watch_condition == "price_crosses_above":
                        if live_price > float(zone.price_high):
                            fired_zone_ids.append(zone.id)
                    elif zone.watch_condition == "price_crosses_below":
                        if live_price < float(zone.price_low):
                            fired_zone_ids.append(zone.id)

                if fired_zone_ids:
                    try:
                        await _trigger_reanalysis(setup, db)
                    except Exception:
                        continue

                    for zone_id in fired_zone_ids:
                        fired = db.query(AlertZone).filter(AlertZone.id == zone_id).one_or_none()
                        if fired is not None:
                            fired.is_active = False
                    db.commit()

            logger.warning("Alert watcher cycle complete: checked %d setups", len(grouped))
        finally:
            db.close()

        await asyncio.sleep(30)


def start_alert_watcher() -> asyncio.Task[None] | None:
    global _watcher_running, _watcher_task

    if _watcher_running and _watcher_task is not None and not _watcher_task.done():
        return _watcher_task

    _watcher_running = True
    _watcher_task = asyncio.create_task(run_alert_watcher())
    return _watcher_task


def stop_alert_watcher() -> None:
    global _watcher_running, _watcher_task

    _watcher_running = False
    if _watcher_task is not None and not _watcher_task.done():
        _watcher_task.cancel()
    _watcher_task = None
