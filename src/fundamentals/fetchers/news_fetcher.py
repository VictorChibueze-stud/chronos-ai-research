from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any
from urllib.parse import quote_plus

import feedparser
from sqlalchemy import cast, String

from src.db.session import SessionLocal
from src.fundamentals.models import EconomicEvent, NewsArticle
from src.fundamentals.sentiment import classify_headline


SNAPSHOT_WINDOWS = {
    "48h": 48,
    "24h": 24,
    "6h": 6,
}
TOLERANCE_MINUTES = 30

NEWS_SOURCES = {
    "crypto": [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
    ],
    "forex": [
        "https://www.forexlive.com/feed/news",
    ],
    "all": [],
}


def _get_market_type(symbol: str) -> str:
    if symbol.endswith("USDT"):
        return "crypto"
    if any(symbol.startswith(fx) for fx in ["EUR", "GBP", "USD", "JPY", "XAU", "CAD", "CHF"]):
        return "forex"
    return "all"


def _fetch_rss(url: str) -> list[dict]:
    """Fetch an RSS feed and return list of {title, link, published} dicts."""
    try:
        feed = feedparser.parse(url)
        articles = []
        for entry in feed.entries[:20]:  # max 20 per feed
            articles.append({
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "published": entry.get("published", ""),
            })
        return articles
    except Exception as e:
        print(f"RSS fetch failed for {url}: {e}")
        return []


def _fetch_google_news(query: str) -> list[dict]:
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    return _fetch_rss(url)


def _parse_published_dt(published_str: str) -> datetime:
    """Parse RSS published string to UTC datetime. Falls back to now() if unparseable."""
    import email.utils
    try:
        parsed = email.utils.parsedate_to_datetime(published_str)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def fetch_news_for_event(event: EconomicEvent, snapshot: str, db: Any) -> int:
    """
    Fetch news articles relevant to an event and store them.
    Returns count of new articles inserted.
    """
    inserted = 0
    seen_urls = set(
        r[0] for r in db.query(NewsArticle.url).filter(
            NewsArticle.event_id == event.id,
            NewsArticle.fetch_snapshot == snapshot,
        ).all()
    )

    for market_symbol in (event.affected_markets or []):
        market_type = _get_market_type(market_symbol)

        # Build article list from relevant sources
        articles = []
        if market_type == "crypto":
            for url in NEWS_SOURCES["crypto"]:
                articles.extend(_fetch_rss(url))
            articles.extend(_fetch_google_news(f"{market_symbol} crypto"))
        elif market_type == "forex":
            for url in NEWS_SOURCES["forex"]:
                articles.extend(_fetch_rss(url))
            articles.extend(_fetch_google_news(f"{event.event_name} forex"))
        else:
            articles.extend(_fetch_google_news(event.event_name))

        for article in articles:
            url = article["url"]
            if not url or url in seen_urls:
                continue

            # Check global dedup across all news_articles
            existing = db.query(NewsArticle.id).filter(NewsArticle.url == url).first()
            if existing:
                seen_urls.add(url)
                continue

            headline = article["title"]
            if not headline:
                continue

            label, score = classify_headline(headline)
            published_at = _parse_published_dt(article["published"])

            db.add(NewsArticle(
                headline=headline,
                source_name="RSS",
                published_at=published_at,
                url=url,
                market_tags=[market_symbol],
                event_id=event.id,
                fetch_snapshot=snapshot,
                sentiment_label=label,
                sentiment_score=score,
                fetched_at=datetime.now(timezone.utc),
            ))
            seen_urls.add(url)
            inserted += 1

    db.commit()
    return inserted


def run_news_check() -> dict:
    """
    Hourly job: check if any upcoming high-impact event is at 48h, 24h, or 6h mark.
    Fetch news for qualifying events if not already fetched for that snapshot.
    """
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    total_inserted = 0
    events_triggered = 0

    try:
        for snapshot_label, hours_out in SNAPSHOT_WINDOWS.items():
            target_time = now + timedelta(hours=hours_out)
            window_start = target_time - timedelta(minutes=TOLERANCE_MINUTES)
            window_end = target_time + timedelta(minutes=TOLERANCE_MINUTES)

            upcoming = db.query(EconomicEvent).filter(
                EconomicEvent.impact_level == "high",
                EconomicEvent.scheduled_at >= window_start,
                EconomicEvent.scheduled_at <= window_end,
                cast(EconomicEvent.affected_markets, String) != "[]",
            ).all()

            for event in upcoming:
                # Check if this snapshot was already fetched
                already_fetched = db.query(NewsArticle).filter(
                    NewsArticle.event_id == event.id,
                    NewsArticle.fetch_snapshot == snapshot_label,
                ).first()

                if already_fetched:
                    continue

                count = fetch_news_for_event(event, snapshot_label, db)
                total_inserted += count
                events_triggered += 1
                print(f"News fetched for {event.event_name} ({snapshot_label}): {count} articles")

    finally:
        db.close()

    return {"events_triggered": events_triggered, "articles_inserted": total_inserted}
