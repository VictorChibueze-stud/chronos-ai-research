"""
Orchestrates the 3-call LLM chain for
fundamentals intelligence per market.

For each monitored non-synthetic market:
1. Get prime impulse start date
2. Fetch and deduplicate headlines from that date
3. Get upcoming economic events
4. Run 3-call chain: filter → cluster → veto
5. Store result in fundamental_stories
6. Update monitored_setups.critical_veto_flag
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.db.session import SessionLocal
from src.db.models import MonitoredSetup
from src.fundamentals.models import FundamentalStory
from src.fundamentals.fetchers.market_news_fetcher import (
    _is_synthetic,
    fetch_news_for_market,
    get_prime_impulse_start,
    get_upcoming_events_for_market,
)
from src.fundamentals.llm.router import call_llm_with_fallback
from src.fundamentals.llm.prompts import (
    CLUSTER_SYSTEM,
    CLUSTER_USER,
    FILTER_SYSTEM,
    FILTER_USER,
    VETO_SYSTEM,
    VETO_USER,
    build_market_description,
)

logger = logging.getLogger(__name__)

# Max headlines per LLM call — keeps free-tier context usage sane.
_MAX_HEADLINES_PER_CALL = 50


def _parse_veto_expiry(
    value: str | None,
) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _batch_headlines(
    articles: list[dict],
    batch_size: int = _MAX_HEADLINES_PER_CALL,
) -> list[list[dict]]:
    """Split articles into equal-sized batches."""
    return [
        articles[i : i + batch_size]
        for i in range(0, len(articles), batch_size)
    ]


def _run_filter_call(
    symbol: str,
    articles: list[dict],
    analysis_date: str,
) -> list[dict]:
    """
    Call 1: classify each headline by relevance and sentiment.
    Drop Noise and Peripheral. May run multiple times if the
    article set exceeds the batch size.
    """
    market_desc = build_market_description(symbol)
    all_filtered: list[dict] = []
    batches = _batch_headlines(articles)

    for batch_num, batch in enumerate(batches):
        headlines_input = [
            {
                "id": f"h_{i:03d}",
                "headline": a["headline"],
                "source": a.get("source", ""),
                "published_at": (
                    a["published_at"].isoformat()
                    if hasattr(a["published_at"], "isoformat")
                    else str(a["published_at"])
                ),
                "url": a.get("url", ""),
                "popularity_count": a.get("popularity_count", 1),
            }
            for i, a in enumerate(batch)
        ]

        user_prompt = FILTER_USER.format(
            market=symbol,
            market_description=market_desc,
            analysis_date=analysis_date,
            headlines_json=json.dumps(headlines_input, indent=2),
        )

        result = call_llm_with_fallback(
            system_prompt=FILTER_SYSTEM,
            user_prompt=user_prompt,
            max_tokens=3000,
            temperature=0.1,
            call_type="filter",
        )

        if result is None:
            logger.warning(
                "Filter call failed for %s batch %d — using all headlines",
                symbol,
                batch_num,
            )
            # Fallback: surface every headline as Contextual/Neutral so
            # the cluster stage still has material to work with.
            for item in headlines_input:
                all_filtered.append(
                    {
                        **item,
                        "relevance": "Contextual",
                        "sentiment": "Neutral",
                    }
                )
            continue

        filtered = result.get("filtered", [])
        all_filtered.extend(filtered)
        logger.info(
            "Filter batch %d for %s: %d → %d headlines after filter",
            batch_num,
            symbol,
            len(batch),
            len(filtered),
        )

    return all_filtered


def _run_cluster_call(
    symbol: str,
    filtered_articles: list[dict],
    window_start: str,
    window_end: str,
) -> list[dict]:
    """
    Call 2: group filtered headlines into story clusters with
    actors and a timeline.
    """
    if not filtered_articles:
        return []

    user_prompt = CLUSTER_USER.format(
        market=symbol,
        window_start=window_start,
        window_end=window_end,
        filtered_json=json.dumps(filtered_articles, indent=2),
    )

    result = call_llm_with_fallback(
        system_prompt=CLUSTER_SYSTEM,
        user_prompt=user_prompt,
        max_tokens=4000,
        temperature=0.2,
        call_type="cluster",
    )

    if result is None:
        logger.warning(
            "Cluster call failed for %s — returning empty stories",
            symbol,
        )
        return []

    stories = result.get("stories", [])
    logger.info(
        "Cluster call for %s: %d headlines → %d stories",
        symbol,
        len(filtered_articles),
        len(stories),
    )
    return stories


def _run_veto_call(
    symbol: str,
    stories: list[dict],
    upcoming_events: list[dict],
    now_utc: str,
) -> dict[str, Any]:
    """
    Call 3: assess critical_veto_flag given stories and upcoming
    events. Default on failure: ALLOW (flag=False).
    """
    user_prompt = VETO_USER.format(
        market=symbol,
        now_utc=now_utc,
        # Limit to 10 stories and 20 events to keep prompt compact.
        stories_json=json.dumps(stories[:10], indent=2),
        upcoming_events_json=json.dumps(upcoming_events[:20], indent=2),
    )

    result = call_llm_with_fallback(
        system_prompt=VETO_SYSTEM,
        user_prompt=user_prompt,
        max_tokens=500,
        temperature=0.1,
        call_type="veto",
    )

    if result is None:
        logger.warning(
            "Veto call failed for %s — defaulting to ALLOW", symbol
        )
        return {
            "critical_veto_flag": False,
            "veto_reason": None,
            "veto_expires_at": None,
            "risk_summary": "Analysis unavailable",
        }

    return result


def _upsert_fundamental_story(
    symbol: str,
    payload: dict,
    prime_impulse_start: datetime | None,
    window_start: datetime,
    window_end: datetime,
    db: Session,
) -> None:
    """Write or update the fundamental_stories row for a symbol."""
    existing = (
        db.query(FundamentalStory)
        .filter(FundamentalStory.symbol == symbol)
        .first()
    )
    now = datetime.now(timezone.utc)

    if existing is None:
        db.add(
            FundamentalStory(
                symbol=symbol,
                prime_impulse_start=prime_impulse_start,
                stories_json=payload,
                critical_veto_flag=payload.get(
                    "critical_veto_flag", False
                ),
                veto_reason=payload.get("veto_reason"),
                veto_expires_at=_parse_veto_expiry(
                    payload.get("veto_expires_at")
                ),
                news_window_start=window_start,
                news_window_end=window_end,
                analyzed_at=now,
                created_at=now,
                updated_at=now,
            )
        )
    else:
        existing.stories_json = payload
        existing.prime_impulse_start = prime_impulse_start
        existing.critical_veto_flag = payload.get(
            "critical_veto_flag", False
        )
        existing.veto_reason = payload.get("veto_reason")
        existing.veto_expires_at = _parse_veto_expiry(
            payload.get("veto_expires_at")
        )
        existing.news_window_start = window_start
        existing.news_window_end = window_end
        existing.analyzed_at = now
        existing.updated_at = now

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(
            "Failed to upsert story for %s: %s", symbol, e
        )


def _update_monitored_veto_flag(
    symbol: str,
    veto_flag: bool,
    analyzed_at: datetime,
    db: Session,
) -> None:
    """Sync veto flag back onto the MonitoredSetup row."""
    setup = (
        db.query(MonitoredSetup)
        .filter(MonitoredSetup.symbol == symbol)
        .first()
    )
    if setup is None:
        return
    setup.critical_veto_flag = veto_flag
    setup.fundamental_analyzed_at = analyzed_at
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(
            "Failed to update veto flag for %s: %s", symbol, e
        )


def process_market(
    symbol: str,
    db: Session,
) -> dict[str, Any]:
    """
    Run the full 3-call fundamentals intelligence chain for one
    market. Returns a summary dict with status and any veto
    decision.
    """
    now = datetime.now(timezone.utc)
    sym = symbol.upper()

    impulse_start = get_prime_impulse_start(sym, db)
    if impulse_start is None:
        logger.info(
            "No prime impulse for %s — skipping", sym
        )
        return {
            "symbol": sym,
            "status": "skipped",
            "reason": "no_prime_impulse",
        }

    if impulse_start.tzinfo is None:
        impulse_start = impulse_start.replace(tzinfo=timezone.utc)

    window_end = now
    analysis_date = now.strftime("%Y-%m-%d")
    now_iso = now.isoformat()

    articles = fetch_news_for_market(sym, impulse_start, db)
    if not articles:
        logger.info(
            "No news found for %s — skipping LLM chain", sym
        )
        return {
            "symbol": sym,
            "status": "skipped",
            "reason": "no_news",
        }

    upcoming_events = get_upcoming_events_for_market(
        sym, impulse_start, db
    )

    # CALL 1 — Filter.
    filtered = _run_filter_call(sym, articles, analysis_date)

    # CALL 2 — Cluster.
    stories = _run_cluster_call(
        sym,
        filtered,
        impulse_start.strftime("%Y-%m-%d"),
        now.strftime("%Y-%m-%d"),
    )

    # CALL 3 — Veto assessment.
    veto_result = _run_veto_call(
        sym, stories, upcoming_events, now_iso
    )

    payload = {
        "market": sym,
        "analysis_date": now_iso,
        "prime_impulse_start": impulse_start.isoformat(),
        "critical_veto_flag": veto_result.get(
            "critical_veto_flag", False
        ),
        "veto_reason": veto_result.get("veto_reason"),
        "veto_expires_at": veto_result.get("veto_expires_at"),
        "risk_summary": veto_result.get("risk_summary", ""),
        "stories": stories,
        "upcoming_events": upcoming_events[:20],
        "article_count": len(articles),
        "filtered_count": len(filtered),
        "story_count": len(stories),
    }

    _upsert_fundamental_story(
        sym,
        payload,
        impulse_start,
        impulse_start,
        window_end,
        db,
    )
    _update_monitored_veto_flag(
        sym,
        veto_result.get("critical_veto_flag", False),
        now,
        db,
    )

    return {
        "symbol": sym,
        "status": "completed",
        "critical_veto_flag": payload["critical_veto_flag"],
        "stories": len(stories),
        "articles_fetched": len(articles),
        "articles_after_filter": len(filtered),
    }


def run_fundamentals_intelligence() -> dict[str, Any]:
    """
    Daily job: process all non-synthetic monitored markets
    sequentially. Called by the APScheduler.
    """
    from src.fundamentals.models import FundamentalAnalysisLog

    job_start = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    processed = 0
    skipped = 0
    vetoed = 0
    llm_calls_before = _get_total_calls_today()

    db = SessionLocal()
    try:
        markets = db.query(MonitoredSetup).all()
        non_synth = [
            m for m in markets if not _is_synthetic(m.symbol)
        ]
        logger.info(
            "Starting fundamentals intelligence for %d non-synthetic markets",
            len(non_synth),
        )

        for setup in non_synth:
            try:
                result = process_market(setup.symbol, db)
                if result["status"] == "completed":
                    processed += 1
                    if result.get("critical_veto_flag"):
                        vetoed += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.warning(
                    "Error processing %s: %s", setup.symbol, e
                )
                skipped += 1

            # Small pause between markets so Google News RSS
            # doesn't throttle us.
            time.sleep(2)

        duration = int(time.perf_counter() - job_start)
        llm_calls_after = _get_total_calls_today()

        db.add(
            FundamentalAnalysisLog(
                run_date=started_at,
                markets_processed=processed,
                markets_skipped=skipped,
                markets_vetoed=vetoed,
                llm_calls_made=llm_calls_after - llm_calls_before,
                llm_calls_failed=0,
                duration_seconds=duration,
                status="completed",
            )
        )
        db.commit()

        logger.info(
            "Fundamentals intelligence complete: %d processed, %d skipped, %d vetoed in %ds",
            processed,
            skipped,
            vetoed,
            duration,
        )
        return {
            "processed": processed,
            "skipped": skipped,
            "vetoed": vetoed,
            "duration_seconds": duration,
        }

    except Exception as e:
        logger.exception(
            "Fundamentals intelligence job failed: %s", e
        )
        return {"error": str(e)}
    finally:
        db.close()


def _get_total_calls_today() -> int:
    """Sum of all LLM calls issued today across the waterfall."""
    from src.fundamentals.llm.router import _quota, _today_utc

    today = _today_utc()
    return sum(
        v["count"]
        for v in _quota.values()
        if v.get("date") == today
    )
