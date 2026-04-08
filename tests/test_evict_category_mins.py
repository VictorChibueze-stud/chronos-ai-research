"""Tests for _evict_to_capacity category minimum slots."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.routers.setups import (
    DEFAULT_CATEGORY_MIN_SLOTS,
    _evict_to_capacity,
    _monitored_setup_category,
    _normalize_scan_settings,
)
from src.db.models import MonitoredSetup
from src.db.session import Base


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _setup(symbol: str, score: float) -> MonitoredSetup:
    now = datetime.now(timezone.utc)
    return MonitoredSetup(
        symbol=symbol,
        htf_timeframe="1h",
        htf_trend_direction="up",
        status="SCANNING",
        trend_score=score,
        structural_state_json={},
        last_checked_at=now,
        created_at=now,
        updated_at=now,
    )


def test_monitored_setup_category_respects_overrides():
    settings = _normalize_scan_settings(
        {
            "deriv_category_overrides": {"ZZZFOREX": "forex"},
            "category_min_slots": dict(DEFAULT_CATEGORY_MIN_SLOTS),
        }
    )
    assert _monitored_setup_category("ZZZFOREX", settings) == "forex"
    assert _monitored_setup_category("BTCUSDT", settings) == "crypto"


def test_evict_swaps_in_forex_when_minimum_requires():
    Session = _session_factory()
    cap = 10
    rows = []
    for i in range(cap):
        rows.append(_setup(f"C{i}USDT", float(100 - i)))
    for i in range(5):
        rows.append(_setup(f"FX{i}", float(50 - i)))

    settings = _normalize_scan_settings(
        {
            "category_min_slots": {
                "forex": 3,
                "commodity": 0,
                "indices": 0,
                "synthetic": 0,
                "crypto": 0,
            },
            "deriv_category_overrides": {f"FX{i}": "forex" for i in range(5)},
        }
    )

    with Session() as db:
        db.add_all(rows)
        db.commit()
        _evict_to_capacity(db, capacity=cap, settings=settings)
        remaining = {r.symbol for r in db.query(MonitoredSetup).all()}

    forex_remaining = {
        s for s in remaining if _monitored_setup_category(s, settings) == "forex"
    }
    assert len(forex_remaining) >= 3
    assert len(remaining) == cap


def test_normalize_category_min_slots_caps_and_scales_sum():
    raw = {
        "forex": 99,
        "commodity": 99,
        "indices": 99,
        "synthetic": 99,
        "crypto": 0,
    }
    out = _normalize_scan_settings({"category_min_slots": raw})["category_min_slots"]
    assert all(0 <= out[k] <= 50 for k in out)
    assert sum(out[k] for k in out if k != "crypto") <= 50
