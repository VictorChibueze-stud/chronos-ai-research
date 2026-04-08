from __future__ import annotations

import bisect
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_

from src.db.models import CandleCache
from src.db.session import SessionLocal
from src.fundamentals.models import EconomicEvent, EventImpactRanking, FundamentalEventImpact


CANDLE_TIMEFRAME = "1h"
PRE_EVENT_HOURS = 24
POST_EVENT_HOURS = 72
MIN_CANDLES_REQUIRED = 12
RECOVERY_THRESHOLD_PCT = 0.20


@dataclass
class _CandlePoint:
    timestamp: datetime
    high: float
    low: float
    close: float


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _window_slice(
    candles: list[_CandlePoint],
    timestamps: list[datetime],
    start_ts: datetime,
    end_ts: datetime,
) -> list[_CandlePoint]:
    left = bisect.bisect_left(timestamps, start_ts)
    right = bisect.bisect_right(timestamps, end_ts)
    return candles[left:right]


def _compute_single_event_market_impact(
    event: EconomicEvent,
    market_symbol: str,
    candles: list[_CandlePoint],
    timestamps: list[datetime],
) -> dict[str, Any] | None:
    scheduled_at = _to_utc(event.scheduled_at)
    window_start = scheduled_at - timedelta(hours=PRE_EVENT_HOURS)
    window_end = scheduled_at + timedelta(hours=POST_EVENT_HOURS)

    in_window = _window_slice(candles, timestamps, window_start, window_end)
    if len(in_window) < MIN_CANDLES_REQUIRED:
        return None

    pre_event = [c for c in in_window if c.timestamp < scheduled_at]
    post_event = [c for c in in_window if c.timestamp >= scheduled_at]
    if len(pre_event) < 6 or not post_event:
        return None

    baseline_range = statistics.mean((c.high - c.low) for c in pre_event)
    if baseline_range < 0.0001:
        return None

    post_max_high = max(c.high for c in post_event)
    post_min_low = min(c.low for c in post_event)
    max_post_event_move = post_max_high - post_min_low
    shock_pct = (max_post_event_move / baseline_range) * 100.0

    last_pre_close = pre_event[-1].close
    tolerance = abs(last_pre_close) * RECOVERY_THRESHOLD_PCT
    recovery_hours = float(POST_EVENT_HOURS)
    for c in post_event:
        if abs(c.close - last_pre_close) <= tolerance:
            delta_h = (c.timestamp - scheduled_at).total_seconds() / 3600.0
            recovery_hours = max(0.0, float(delta_h))
            break

    return {
        "market_symbol": market_symbol,
        "event_category": event.event_category,
        "shock_pct": float(shock_pct),
        "recovery_hours": float(recovery_hours),
    }


def compute_impact_for_event(
    db: Any,
    event: EconomicEvent,
    timeframe: str,
    symbol_candles: dict[str, list[_CandlePoint]] | None = None,
    symbol_timestamps: dict[str, list[datetime]] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    markets = [str(m).upper() for m in (event.affected_markets or []) if m]
    if not markets:
        return results

    for market_symbol in markets:
        if symbol_candles is not None and symbol_timestamps is not None:
            candles = symbol_candles.get(market_symbol, [])
            timestamps = symbol_timestamps.get(market_symbol, [])
        else:
            rows = (
                db.query(CandleCache)
                .filter(
                    CandleCache.symbol == market_symbol,
                    CandleCache.timeframe == timeframe,
                )
                .order_by(CandleCache.timestamp.asc())
                .all()
            )
            candles = [
                _CandlePoint(
                    timestamp=_to_utc(r.timestamp),
                    high=float(r.high),
                    low=float(r.low),
                    close=float(r.close),
                )
                for r in rows
            ]
            timestamps = [c.timestamp for c in candles]

        if not candles:
            continue

        item = _compute_single_event_market_impact(event, market_symbol, candles, timestamps)
        if item is not None:
            results.append(item)

    return results


def run_historical_impact_batch() -> dict[str, int]:
    db = SessionLocal()
    now_utc = datetime.now(timezone.utc)
    try:
        events = (
            db.query(EconomicEvent)
            .filter(
                and_(
                    EconomicEvent.impact_level == "high",
                    EconomicEvent.scheduled_at < now_utc,
                )
            )
            .order_by(EconomicEvent.scheduled_at.asc())
            .all()
        )
        eligible_events = [e for e in events if isinstance(e.affected_markets, list) and len(e.affected_markets) > 0]

        symbol_to_events: dict[str, list[EconomicEvent]] = defaultdict(list)
        for event in eligible_events:
            for symbol in event.affected_markets:
                if not symbol:
                    continue
                symbol_to_events[str(symbol).upper()].append(event)

        symbol_candles: dict[str, list[_CandlePoint]] = {}
        symbol_timestamps: dict[str, list[datetime]] = {}
        for symbol in symbol_to_events.keys():
            rows = (
                db.query(CandleCache)
                .filter(
                    CandleCache.symbol == symbol,
                    CandleCache.timeframe == CANDLE_TIMEFRAME,
                )
                .order_by(CandleCache.timestamp.asc())
                .all()
            )
            pts = [
                _CandlePoint(
                    timestamp=_to_utc(r.timestamp),
                    high=float(r.high),
                    low=float(r.low),
                    close=float(r.close),
                )
                for r in rows
            ]
            symbol_candles[symbol] = pts
            symbol_timestamps[symbol] = [p.timestamp for p in pts]

        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        total = len(eligible_events)
        for idx, event in enumerate(eligible_events, start=1):
            impacts = compute_impact_for_event(
                db,
                event,
                CANDLE_TIMEFRAME,
                symbol_candles=symbol_candles,
                symbol_timestamps=symbol_timestamps,
            )
            for impact in impacts:
                key = (impact["market_symbol"], impact["event_category"])
                grouped[key].append(impact)

            if idx % 100 == 0:
                print(f"Processed {idx}/{total} events...")

        now_compute = datetime.now(timezone.utc)
        impacts_written = 0
        for (market_symbol, event_category), rows in grouped.items():
            if len(rows) < 3:
                continue

            median_shock_pct = float(statistics.median(r["shock_pct"] for r in rows))
            median_recovery_hours = float(statistics.median(r["recovery_hours"] for r in rows))
            sample_count = len(rows)

            existing = (
                db.query(FundamentalEventImpact)
                .filter(
                    FundamentalEventImpact.market_symbol == market_symbol,
                    FundamentalEventImpact.event_category == event_category,
                )
                .one_or_none()
            )
            if existing is None:
                db.add(
                    FundamentalEventImpact(
                        market_symbol=market_symbol,
                        event_category=event_category,
                        sample_count=sample_count,
                        median_shock_pct=median_shock_pct,
                        median_recovery_hours=median_recovery_hours,
                        computed_at=now_compute,
                    )
                )
            else:
                existing.sample_count = sample_count
                existing.median_shock_pct = median_shock_pct
                existing.median_recovery_hours = median_recovery_hours
                existing.computed_at = now_compute
            impacts_written += 1

        db.flush()

        by_market: dict[str, list[FundamentalEventImpact]] = defaultdict(list)
        impact_rows = db.query(FundamentalEventImpact).all()
        for row in impact_rows:
            by_market[row.market_symbol].append(row)

        rankings_written = 0
        for market_symbol, rows in by_market.items():
            ranked_rows = sorted(rows, key=lambda r: r.median_shock_pct, reverse=True)
            for rank, row in enumerate(ranked_rows, start=1):
                existing_rank = (
                    db.query(EventImpactRanking)
                    .filter(
                        EventImpactRanking.market_symbol == market_symbol,
                        EventImpactRanking.event_category == row.event_category,
                    )
                    .one_or_none()
                )
                if existing_rank is None:
                    db.add(
                        EventImpactRanking(
                            market_symbol=market_symbol,
                            event_category=row.event_category,
                            rank=rank,
                            median_shock_pct=float(row.median_shock_pct),
                            occurrence_count=int(row.sample_count),
                            computed_at=now_compute,
                        )
                    )
                else:
                    existing_rank.rank = rank
                    existing_rank.median_shock_pct = float(row.median_shock_pct)
                    existing_rank.occurrence_count = int(row.sample_count)
                    existing_rank.computed_at = now_compute
                rankings_written += 1

        db.commit()
        return {
            "total_events_processed": total,
            "total_symbols_analysed": len(by_market),
            "total_rankings_written": rankings_written,
            "total_impacts_written": impacts_written,
        }
    finally:
        db.close()
