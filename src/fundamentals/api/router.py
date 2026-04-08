from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import cast, String
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.fundamentals.models import EconomicEvent, EventImpactRanking, NewsArticle
from src.fundamentals.event_gate import is_trading_clear

router = APIRouter(prefix="/api/fundamentals", tags=["fundamentals"])


@router.get("/events/{symbol}")
def get_market_events(symbol: str, db: Session = Depends(get_db)):
    """
    Get upcoming high/medium impact economic events affecting a symbol,
    along with the current trading clear status.
    """
    now = datetime.now(timezone.utc)
    is_clear, reason = is_trading_clear(symbol, now)

    upcoming = (
        db.query(EconomicEvent)
        .filter(
            EconomicEvent.scheduled_at > now,
            EconomicEvent.impact_level.in_(["high", "medium"]),
        )
        .order_by(EconomicEvent.scheduled_at.asc())
        .all()
    )

    relevant = []
    for event in upcoming:
        # Check if symbol appears in affected_markets JSON list
        affected = event.affected_markets or []
        if symbol not in affected:
            continue

        # Look up ranking for this symbol + category
        ranking = (
            db.query(EventImpactRanking)
            .filter(
                EventImpactRanking.market_symbol == symbol,
                EventImpactRanking.event_category == event.event_category,
            )
            .first()
        )

        relevant.append({
            "name": event.event_name,
            "category": event.event_category,
            "scheduled_at": event.scheduled_at.isoformat(),
            "impact_level": event.impact_level,
            "rank": ranking.rank if ranking else None,
            "currency": event.currency,
        })

        # Limit to 3 upcoming events
        if len(relevant) >= 3:
            break

    return {
        "symbol": symbol,
        "blackout_active": not is_clear,
        "blackout_reason": reason,
        "next_events": relevant,
    }


@router.get("/news/{symbol}")
def get_market_news(symbol: str, db: Session = Depends(get_db)):
    """
    Get recent news articles tagged with the symbol, ordered by recency.
    """
    articles = (
        db.query(NewsArticle)
        .filter(cast(NewsArticle.market_tags, String).contains(symbol))
        .order_by(NewsArticle.published_at.desc())
        .limit(5)
        .all()
    )

    return {
        "symbol": symbol,
        "articles": [
            {
                "headline": a.headline,
                "source_name": a.source_name,
                "published_at": a.published_at.isoformat(),
                "sentiment_label": a.sentiment_label,
                "sentiment_score": a.sentiment_score,
                "url": a.url,
            }
            for a in articles
        ],
    }
