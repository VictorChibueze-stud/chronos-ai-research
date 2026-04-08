from __future__ import annotations

import re
from datetime import datetime, timezone
from html import unescape
from typing import Any
from urllib.parse import quote_plus
from xml.etree import ElementTree

import requests

from src.db.session import SessionLocal
from src.fundamentals.market_mapping import get_affected_markets, get_category_from_event_name
from src.fundamentals.models import EconomicEvent


CALENDAR_QUERIES = [
    "Fed interest rate decision 2026",
    "FOMC meeting 2026",
    "US CPI release 2026",
    "US Non-Farm Payroll 2026",
    "ECB rate decision 2026",
    "Bank of England rate decision 2026",
]

KNOWN_2026_EVENTS = [
    {
        "name": "FOMC Rate Decision",
        "category": "RATE_DECISION",
        "currency": "USD",
        "dates": [
            "2026-01-29",
            "2026-03-19",
            "2026-05-07",
            "2026-06-18",
            "2026-07-30",
            "2026-09-17",
            "2026-10-29",
            "2026-12-10",
        ],
        "time_utc": "19:00",
        "impact": "high",
    },
    {
        "name": "ECB Rate Decision",
        "category": "RATE_DECISION",
        "currency": "EUR",
        "dates": [
            "2026-01-30",
            "2026-03-05",
            "2026-04-17",
            "2026-06-04",
            "2026-07-23",
            "2026-09-10",
            "2026-10-22",
            "2026-12-03",
        ],
        "time_utc": "13:15",
        "impact": "high",
    },
]

_DATE_PATTERNS = [
    re.compile(r"\b(202\d)-(\d{2})-(\d{2})\b"),
    re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},\s*202\d\b", re.IGNORECASE),
]


def _parse_datetime(date_str: str, hhmm: str) -> datetime:
    dt_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    hour, minute = hhmm.split(":", maxsplit=1)
    return datetime(
        dt_date.year,
        dt_date.month,
        dt_date.day,
        int(hour),
        int(minute),
        tzinfo=timezone.utc,
    )


def _event_currency_from_text(text: str) -> str:
    t = text.lower()
    if "ecb" in t or "euro" in t:
        return "EUR"
    if "bank of england" in t or "boe" in t or "uk" in t:
        return "GBP"
    return "USD"


def _extract_date(text: str) -> str | None:
    for pattern in _DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        found = m.group(0)
        if pattern.pattern.startswith("\\b(202"):
            return found
        try:
            parsed = datetime.strptime(found, "%B %d, %Y")
        except ValueError:
            parsed = datetime.strptime(found, "%b %d, %Y")
        return parsed.strftime("%Y-%m-%d")
    return None


def _guess_event_name(title: str, description: str) -> str:
    t = f"{title} {description}".lower()
    if "fomc" in t or "fed" in t and "rate" in t:
        return "FOMC Rate Decision"
    if "cpi" in t or "consumer price" in t:
        return "Consumer Price Index"
    if "non-farm" in t or "nonfarm" in t or "payroll" in t:
        return "Employment Situation"
    if "ecb" in t and "rate" in t:
        return "ECB Rate Decision"
    if "bank of england" in t and "rate" in t:
        return "BOE Rate Decision"
    return title[:255]


def _fetch_google_rss_items(query: str) -> list[dict[str, str]]:
    url = (
        "https://news.google.com/rss/search?q="
        f"{quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    )
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    root = ElementTree.fromstring(response.content)
    out: list[dict[str, str]] = []
    for item in root.findall("./channel/item"):
        title = unescape(item.findtext("title") or "")
        description = unescape(item.findtext("description") or "")
        pub_date = item.findtext("pubDate") or ""
        out.append({"title": title, "description": description, "pub_date": pub_date})
    return out


def _events_from_google_signal() -> list[EconomicEvent]:
    out: list[EconomicEvent] = []
    for query in CALENDAR_QUERIES:
        try:
            items = _fetch_google_rss_items(query)
        except Exception:
            continue
        for item in items:
            title = item.get("title", "")
            description = item.get("description", "")
            merged = f"{title} {description}"
            date_str = _extract_date(merged)
            if not date_str:
                continue

            event_name = _guess_event_name(title, description)
            currency = _event_currency_from_text(merged)
            mapped_category = get_category_from_event_name(event_name)
            category = mapped_category if mapped_category != "UNKNOWN" else "RATE_DECISION"
            scheduled_at = _parse_datetime(date_str, "00:00")

            out.append(
                EconomicEvent(
                    event_name=event_name,
                    event_category=category,
                    source="google_news",
                    scheduled_at=scheduled_at,
                    impact_level="medium",
                    currency=currency,
                    forecast_value=None,
                    actual_value=None,
                    previous_value=None,
                    affected_markets=get_affected_markets(currency),
                    fetched_at=datetime.now(timezone.utc),
                )
            )
    return out


def _events_from_known_schedule() -> list[EconomicEvent]:
    out: list[EconomicEvent] = []
    for event in KNOWN_2026_EVENTS:
        name = str(event["name"])
        category = str(event["category"])
        currency = str(event["currency"])
        hhmm = str(event["time_utc"])
        impact = str(event["impact"])
        for d in event["dates"]:
            scheduled_at = _parse_datetime(str(d), hhmm)
            out.append(
                EconomicEvent(
                    event_name=name,
                    event_category=category,
                    source="schedule",
                    scheduled_at=scheduled_at,
                    impact_level=impact,
                    currency=currency,
                    forecast_value=None,
                    actual_value=None,
                    previous_value=None,
                    affected_markets=get_affected_markets(currency),
                    fetched_at=datetime.now(timezone.utc),
                )
            )
    return out


def fetch_and_store_calendar_events() -> int:
    db = SessionLocal()
    inserted = 0
    try:
        existing_keys = {
            (name, scheduled_at)
            for name, scheduled_at in db.query(
                EconomicEvent.event_name,
                EconomicEvent.scheduled_at,
            ).all()
        }

        for event in _events_from_google_signal() + _events_from_known_schedule():
            key = (event.event_name, event.scheduled_at)
            if key in existing_keys:
                continue
            db.add(event)
            existing_keys.add(key)
            inserted += 1
        db.commit()
        return inserted
    finally:
        db.close()
