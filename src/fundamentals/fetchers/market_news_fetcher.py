"""
News fetcher anchored to prime impulse start.

For each monitored non-synthetic market,
fetches Google News RSS headlines from
impulse_start_timestamp to now.

Deduplicates using 8-word headline fingerprint
before storing. Keeps up to 3 representative
articles per duplicate group plus a
popularity_count so the LLM knows how many
outlets covered each story.

No external API key required.
"""
from __future__ import annotations

import logging
import re  # noqa: F401 — reserved for future regex-based headline normalization
import string
from datetime import datetime, timezone, timedelta  # noqa: F401 — timedelta used inside helpers
from urllib.parse import quote_plus

import feedparser
import requests  # noqa: F401 — reserved for non-feedparser HTTP fallbacks
from sqlalchemy.orm import Session

from src.db.session import SessionLocal  # noqa: F401 — re-exported for callers/tests
from src.db.models import MonitoredSetup  # noqa: F401 — re-exported for callers/tests
from src.fundamentals.models import NewsArticle
from src.db.models import PrimeImpulseStructure

logger = logging.getLogger(__name__)

# Stop words to strip before fingerprinting.
_STOP_WORDS = frozenset(
    {
        "the", "a", "an", "is", "are", "was", "were",
        "has", "have", "had", "be", "been", "being",
        "in", "on", "at", "to", "for", "of", "and",
        "or", "but", "with", "by", "from", "as",
        "its", "it", "this", "that", "will", "would",
        "could", "should", "may", "might", "says",
        "said", "after", "before", "over", "under",
        "new", "us", "up", "out",
    }
)

# Synthetic market markers.
_SYNTHETIC_MARKERS = (
    "1HZ", "R_", "BOOM", "CRASH", "STEP", "JUMP", "RANGE"
)


def _is_synthetic(symbol: str) -> bool:
    s = symbol.upper()
    return any(m in s for m in _SYNTHETIC_MARKERS)


def _build_search_query(symbol: str) -> list[str]:
    """
    Build Google News RSS search queries for a given market symbol.

    Returns a list of query strings — multiple queries capture
    more relevant news.
    """
    sym = symbol.upper()

    # Forex pairs — FRXEURUSD → EUR USD.
    if sym.startswith("FRX"):
        base = sym[3:6]
        quote = sym[6:9]
        return [
            f"{base} {quote} forex",
            f"{base} {quote} exchange rate",
        ]

    # XAUUSD (gold).
    if "XAU" in sym:
        return ["gold price XAU", "gold market"]

    # Crypto USDT pairs — BTCUSDT.
    if sym.endswith("USDT"):
        coin = sym.replace("USDT", "")
        return [
            f"{coin} crypto price",
            f"{coin} cryptocurrency",
        ]

    # US / major indices.
    if sym in ("SPX500", "SPX", "US500"):
        return ["S&P 500 index", "SPX market"]
    if sym in ("NAS100", "NASDAQ"):
        return ["Nasdaq 100 index", "tech stocks"]
    if sym in ("US30", "DOW", "DJIA"):
        return ["Dow Jones index", "DJIA market"]
    if sym in ("UK100", "FTSE"):
        return ["FTSE 100 index", "UK market"]

    # Equity CFDs — assume ticker.
    return [
        f"{sym} stock",
        f"{sym} earnings news",
    ]


def _fingerprint(headline: str) -> str:
    """
    Normalize headline and return an 8-word fingerprint for
    deduplication.
    """
    text = headline.lower()
    text = text.translate(
        str.maketrans("", "", string.punctuation)
    )
    words = [
        w for w in text.split()
        if w not in _STOP_WORDS and len(w) > 2
    ]
    return " ".join(words[:8])


def _fetch_google_news_rss(
    query: str,
    since_date: datetime,
    max_results: int = 50,
) -> list[dict]:
    """
    Fetch Google News RSS for a query.

    Returns a list of ``{headline, url, source, published_at}``
    dicts, filtered to entries published on or after ``since_date``.
    """
    url = (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )
    try:
        feed = feedparser.parse(url)
        articles: list[dict] = []
        for entry in feed.entries[:max_results]:
            published = entry.get("published", "")
            try:
                from email.utils import parsedate_to_datetime

                pub_dt = parsedate_to_datetime(published).astimezone(
                    timezone.utc
                )
            except Exception:
                pub_dt = datetime.now(timezone.utc)

            if since_date.tzinfo is None:
                since_date = since_date.replace(tzinfo=timezone.utc)
            if pub_dt < since_date:
                continue

            articles.append(
                {
                    "headline": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "source": entry.get("source", {}).get(
                        "title", "RSS"
                    ),
                    "published_at": pub_dt,
                }
            )
        return articles
    except Exception as e:
        logger.warning(
            "Google News RSS fetch failed for query '%s': %s",
            query,
            e,
        )
        return []


def _deduplicate_articles(articles: list[dict]) -> list[dict]:
    """
    Deduplicate articles by 8-word headline fingerprint.

    For each group of similar headlines, keep up to 3 articles
    and record ``popularity_count`` = total group size. This
    prevents the LLM from seeing 40 identical Reuters/Bloomberg
    rephrases of the same story.
    """
    groups: dict[str, list[dict]] = {}

    for article in articles:
        fp = _fingerprint(article["headline"])
        if not fp:
            continue
        groups.setdefault(fp, []).append(article)

    result: list[dict] = []
    for fp, group in groups.items():
        # Sort by date descending so the most recent is kept first.
        group.sort(key=lambda x: x["published_at"], reverse=True)
        popularity = len(group)
        for article in group[:3]:
            result.append(
                {
                    **article,
                    "popularity_count": popularity,
                    "fingerprint": fp,
                }
            )

    result.sort(key=lambda x: x["published_at"])
    return result


def fetch_news_for_market(
    symbol: str,
    since_date: datetime,
    db: Session,
    max_per_query: int = 50,
) -> list[dict]:
    """
    Fetch and deduplicate news for a market from ``since_date``
    through now.

    Returns a deduplicated article list (with ``popularity_count``)
    ready for LLM input. Does NOT write to the database — the
    caller decides what to store.
    """
    queries = _build_search_query(symbol)
    all_articles: list[dict] = []
    seen_urls: set[str] = set()

    for query in queries:
        articles = _fetch_google_news_rss(
            query, since_date, max_per_query
        )
        for a in articles:
            if a["url"] and a["url"] not in seen_urls:
                seen_urls.add(a["url"])
                all_articles.append(a)

    deduplicated = _deduplicate_articles(all_articles)
    logger.info(
        "Fetched news for %s: %d raw → %d after dedup",
        symbol,
        len(all_articles),
        len(deduplicated),
    )
    return deduplicated


def get_prime_impulse_start(
    symbol: str,
    db: Session,
) -> datetime | None:
    """
    Get the prime impulse start timestamp for a market.

    Returns ``None`` if no prime impulse row exists yet.
    """
    impulse = (
        db.query(PrimeImpulseStructure)
        .filter(PrimeImpulseStructure.symbol == (sym := symbol.upper()))  # noqa: F841
        .order_by(PrimeImpulseStructure.computed_at.desc())
        .first()
    )
    if impulse is None:
        return None
    return impulse.impulse_start_timestamp


def store_raw_articles(
    symbol: str,
    articles: list[dict],
    db: Session,
) -> int:
    """
    Store deduplicated articles to the ``news_articles`` table for
    a market. Skips URLs already stored for this market.
    Returns count of new rows inserted.
    """
    # Check globally — NewsArticle.url has a
    # global unique constraint so we must check
    # across all markets not just this one
    existing_urls = set(
        r[0] for r in
        db.query(NewsArticle.url).all()
    )

    inserted = 0
    for article in articles:
        url = article.get("url", "")
        if not url or url in existing_urls:
            continue
        existing_urls.add(url)

        db.add(
            NewsArticle(
                headline=article["headline"][:500],
                source_name=article.get("source", "RSS")[:100],
                published_at=article["published_at"],
                url=url,
                market_tags=[symbol],
                event_id=None,
                # NOTE: fetch_snapshot is String(10); use short tag.
                fetch_snapshot="mkt_intel",
                # Legacy fields — neutral because the LLM layer in
                # fundamentals/llm/processor.py is the source of truth.
                sentiment_label="neutral",
                sentiment_score=0.0,
                fetched_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
            )
        )
        inserted += 1

    if inserted > 0:
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(
                "Failed to store articles for %s: %s", symbol, e
            )
            return 0

    return inserted


def get_upcoming_events_for_market(
    symbol: str,
    since_date: datetime,
    db: Session,
) -> list[dict]:
    """
    Get economic events relevant to this market from ``since_date``
    through 30 days ahead.

    First queries the existing ``economic_events`` table. If zero
    events are found for this market in the window, attempts to
    refresh calendar data and re-queries.
    """
    from src.fundamentals.models import EconomicEvent
    from datetime import timedelta
    from sqlalchemy import cast, String

    now = datetime.now(timezone.utc)
    window_end = now + timedelta(days=30)

    if since_date.tzinfo is None:
        since_date = since_date.replace(tzinfo=timezone.utc)

    events = (
        db.query(EconomicEvent)
        .filter(
            EconomicEvent.scheduled_at >= since_date,
            EconomicEvent.scheduled_at <= window_end,
            cast(EconomicEvent.affected_markets, String).contains(symbol),
        )
        .order_by(EconomicEvent.scheduled_at.asc())
        .all()
    )

    if not events:
        logger.info(
            "No events found for %s in window "
            "— attempting background calendar "
            "refresh with 15s timeout",
            symbol,
        )
        import threading as _cal_threading

        refresh_done = _cal_threading.Event()
        refresh_error: list[str] = []

        def _do_refresh():
            try:
                from src.fundamentals.fetchers.economic_calendar import (
                    fetch_and_store_calendar_events,
                )

                fetch_and_store_calendar_events()
            except Exception as e:
                refresh_error.append(str(e))
            finally:
                refresh_done.set()

        t = _cal_threading.Thread(
            target=_do_refresh,
            daemon=True,
        )
        t.start()
        completed = refresh_done.wait(timeout=15)

        if not completed:
            logger.warning(
                "Calendar refresh timed out "
                "for %s — using empty events",
                symbol,
            )
        elif refresh_error:
            logger.warning(
                "Calendar refresh failed for "
                "%s: %s — using empty events",
                symbol,
                refresh_error[0],
            )
        else:
            # Re-query after successful refresh
            try:
                events = (
                    db.query(EconomicEvent)
                    .filter(
                        EconomicEvent.scheduled_at
                        >= since_date,
                        EconomicEvent.scheduled_at
                        <= window_end,
                        cast(
                            EconomicEvent.affected_markets,
                            String,
                        ).contains(symbol),
                    )
                    .order_by(
                        EconomicEvent.scheduled_at
                    )
                    .all()
                )
            except Exception as e:
                logger.warning(
                    "Re-query after refresh "
                    "failed for %s: %s",
                    symbol,
                    e,
                )

    return [
        {
            "event_name": e.event_name,
            "event_category": e.event_category,
            "scheduled_at": e.scheduled_at.isoformat(),
            "impact_level": e.impact_level,
            "currency": e.currency,
            "forecast_value": e.forecast_value,
            "actual_value": e.actual_value,
        }
        for e in events
    ]
