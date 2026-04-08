from datetime import datetime, timezone, timedelta
from typing import Optional

from src.db.session import SessionLocal
from src.fundamentals.models import EconomicEvent, EventImpactRanking


def _get_blackout_window(rank: Optional[int], impact_level: str) -> tuple[int, int]:
    """Returns (before_hours, after_hours) for a given rank and impact level."""
    if rank is not None:
        if rank <= 3:
            return (4, 8)
        elif rank <= 7:
            return (2, 4)
        else:
            return (1, 2)
    # fallback when not in ranking table
    if impact_level == "high":
        return (2, 4)
    elif impact_level == "medium":
        return (1, 2)
    else:
        return (0, 0)


def is_trading_clear(market_symbol: str, at_time: datetime) -> tuple[bool, Optional[str]]:
    """
    Check whether trading is clear for a market at a given time.
    Returns (True, None) if clear.
    Returns (False, reason_string) if in a blackout window.
    Must complete in under 50ms.
    """
    db = SessionLocal()
    try:
        # Use a wide search window (max possible blackout = 4h before + 8h after)
        search_start = at_time - timedelta(hours=8)
        search_end = at_time + timedelta(hours=4)

        # Find all high-impact events near this time that affect this market
        events = db.query(EconomicEvent).filter(
            EconomicEvent.impact_level.in_(["high", "medium"]),
            EconomicEvent.scheduled_at >= search_start,
            EconomicEvent.scheduled_at <= search_end,
        ).all()

        for event in events:
            # Check if this market is in the event's affected_markets list
            if market_symbol not in (event.affected_markets or []):
                continue

            # Look up rank for this (market, category) pair
            ranking = db.query(EventImpactRanking).filter(
                EventImpactRanking.market_symbol == market_symbol,
                EventImpactRanking.event_category == event.event_category,
            ).first()

            rank = ranking.rank if ranking else None
            before_hours, after_hours = _get_blackout_window(rank, event.impact_level)

            if before_hours == 0 and after_hours == 0:
                continue

            window_start = event.scheduled_at - timedelta(hours=before_hours)
            window_end = event.scheduled_at + timedelta(hours=after_hours)

            if window_start <= at_time <= window_end:
                # Calculate time remaining or time since event
                if at_time < event.scheduled_at:
                    delta = event.scheduled_at - at_time
                    timing = f"in {int(delta.total_seconds() // 3600)}h {int((delta.total_seconds() % 3600) // 60)}m"
                else:
                    delta = at_time - event.scheduled_at
                    timing = f"{int(delta.total_seconds() // 3600)}h {int((delta.total_seconds() % 3600) // 60)}m ago"

                rank_str = f"rank {rank}" if rank else "unranked"
                reason = (
                    f"BLACKOUT: {event.event_name} {timing} "
                    f"({rank_str} for {market_symbol}) — "
                    f"window closes at {window_end.strftime('%H:%M UTC')}"
                )
                return (False, reason)

        return (True, None)

    finally:
        db.close()
