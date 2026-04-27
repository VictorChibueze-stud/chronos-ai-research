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
def get_market_news(
    symbol: str,
    db: Session = Depends(get_db),
):
    """
    Returns LLM-generated story clusters for a market. Falls back
    to raw articles if LLM analysis has not run yet.
    """
    from src.fundamentals.models import FundamentalStory, NewsArticle

    sym = symbol.strip().upper()

    # Try LLM stories first.
    story = (
        db.query(FundamentalStory)
        .filter(FundamentalStory.symbol == sym)
        .first()
    )

    if story is not None:
        payload = story.stories_json or {}
        return {
            "symbol": sym,
            "mode": "llm_stories",
            "critical_veto_flag": story.critical_veto_flag,
            "veto_reason": story.veto_reason,
            "risk_summary": payload.get("risk_summary", ""),
            "analyzed_at": (
                story.analyzed_at.isoformat()
                if story.analyzed_at
                else None
            ),
            "prime_impulse_start": (
                story.prime_impulse_start.isoformat()
                if story.prime_impulse_start
                else None
            ),
            "stories": payload.get("stories", []),
            "upcoming_events": payload.get("upcoming_events", []),
            "article_count": payload.get("article_count", 0),
        }

    # Fallback: return raw articles with legacy sentiment labels.
    # NOTE: market_tags is stored as JSON (not JSONB); the cast-to-text
    # + .contains pattern matches the existing working query.
    articles = (
        db.query(NewsArticle)
        .filter(cast(NewsArticle.market_tags, String).contains(sym))
        .order_by(NewsArticle.published_at.desc())
        .limit(20)
        .all()
    )
    return {
        "symbol": sym,
        "mode": "raw_articles",
        "critical_veto_flag": False,
        "veto_reason": None,
        "risk_summary": None,
        "analyzed_at": None,
        "prime_impulse_start": None,
        "stories": [],
        "upcoming_events": [],
        "articles": [
            {
                "headline": a.headline,
                "source_name": a.source_name,
                "published_at": a.published_at.isoformat(),
                "url": a.url,
                "sentiment_label": a.sentiment_label,
            }
            for a in articles
        ],
    }
