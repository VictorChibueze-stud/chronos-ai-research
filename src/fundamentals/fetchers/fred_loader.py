from __future__ import annotations

import os
from datetime import datetime, time, timezone

import requests
from dotenv import load_dotenv

from src.db.session import SessionLocal
from src.fundamentals.market_mapping import get_affected_markets, get_category_from_event_name
from src.fundamentals.models import EconomicEvent


load_dotenv()


# Confirmed from FRED API metadata queries.
FRED_RELEASES: list[dict[str, str | int]] = [
    {"release_id": 50, "event_name": "Employment Situation", "fallback_category": "NFP"},
    {"release_id": 10, "event_name": "Consumer Price Index", "fallback_category": "CPI"},
    {"release_id": 53, "event_name": "Gross Domestic Product", "fallback_category": "GDP"},
    {
        "release_id": 9,
        "event_name": "Advance Monthly Sales for Retail and Food Services",
        "fallback_category": "RETAIL_SALES",
    },
    {"release_id": 101, "event_name": "FOMC Press Release", "fallback_category": "RATE_DECISION"},
]


def _scheduled_time_for_category(category: str) -> time:
    c = (category or "").upper()
    if c == "RATE_DECISION":
        return time(19, 0)
    if c == "GDP":
        return time(12, 30)
    return time(13, 30)


def _fetch_release_dates(release_id: int, api_key: str) -> list[str]:
    url = "https://api.stlouisfed.org/fred/release/dates"
    params = {
        "release_id": release_id,
        "api_key": api_key,
        "file_type": "json",
        "realtime_start": "2015-01-01",
    }
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json() or {}
    out: list[str] = []
    for row in payload.get("release_dates", []):
        date_str = row.get("date")
        if isinstance(date_str, str) and date_str:
            out.append(date_str)
    return out


def _build_scheduled_at(date_str: str, event_category: str) -> datetime:
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    t = _scheduled_time_for_category(event_category)
    return datetime.combine(d, t, tzinfo=timezone.utc)


def load_fred_historical_events() -> int:
    api_key = (os.getenv("FRED_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("FRED_API_KEY is required to load FRED historical events")

    db = SessionLocal()
    inserted = 0
    try:
        affected_markets = get_affected_markets("USD")

        for rel in FRED_RELEASES:
            release_id = int(rel["release_id"])
            event_name = str(rel["event_name"])
            fallback_category = str(rel["fallback_category"])

            mapped_category = get_category_from_event_name(event_name)
            event_category = mapped_category if mapped_category != "UNKNOWN" else fallback_category

            for date_str in _fetch_release_dates(release_id, api_key):
                scheduled_at = _build_scheduled_at(date_str, event_category)

                exists = (
                    db.query(EconomicEvent.id)
                    .filter(
                        EconomicEvent.event_name == event_name,
                        EconomicEvent.scheduled_at == scheduled_at,
                    )
                    .first()
                    is not None
                )
                if exists:
                    continue

                db.add(
                    EconomicEvent(
                        event_name=event_name,
                        event_category=event_category,
                        source="fred",
                        scheduled_at=scheduled_at,
                        impact_level="high",
                        currency="USD",
                        forecast_value=None,
                        actual_value=None,
                        previous_value=None,
                        affected_markets=affected_markets,
                        fetched_at=datetime.now(timezone.utc),
                    )
                )
                inserted += 1

        db.commit()
        return inserted
    finally:
        db.close()
