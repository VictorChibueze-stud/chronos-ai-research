"""Tests for SQL-backed candle cache (src.cache.candle_store)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.cache import candle_store
from src.cache.candle_store import (
    get_earliest_cached_timestamp,
    get_last_cached_timestamp,
    lookback_start_time,
    refresh_candles,
)
from src.core.features import Candle
from src.db.models import CandleCache
from src.db.session import Base


def _memory_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_get_last_cached_timestamp_candle_empty_returns_none():
    Session = _memory_session()
    with Session() as db:
        assert get_last_cached_timestamp("BTCUSDT", "1h", db) is None


def test_get_last_cached_timestamp_candle_returns_latest_open_time():
    Session = _memory_session()
    now = datetime.now(timezone.utc)
    t1 = now.replace(microsecond=0)
    t2 = t1.replace(year=t1.year + 1)
    with Session() as db:
        for ts in (t1, t2):
            db.add(
                CandleCache(
                    symbol="BTCUSDT",
                    timeframe="1h",
                    timestamp=ts,
                    open=1.0,
                    high=2.0,
                    low=0.5,
                    close=1.5,
                    volume=100.0,
                    updated_at=now,
                )
            )
        db.commit()
        got = get_last_cached_timestamp("btcusdt", "1H", db)
        assert got == t2
        assert got.tzinfo is not None


def test_get_earliest_cached_timestamp_empty_returns_none():
    Session = _memory_session()
    with Session() as db:
        assert get_earliest_cached_timestamp("ETHUSDT", "4h", db) is None


def test_get_earliest_cached_timestamp_returns_earliest_open_time():
    Session = _memory_session()
    now = datetime.now(timezone.utc)
    t1 = now.replace(microsecond=0)
    t2 = t1.replace(year=t1.year + 1)
    with Session() as db:
        for ts in (t1, t2):
            db.add(
                CandleCache(
                    symbol="ETHUSDT",
                    timeframe="4h",
                    timestamp=ts,
                    open=1.0,
                    high=2.0,
                    low=0.5,
                    close=1.5,
                    volume=100.0,
                    updated_at=now,
                )
            )
        db.commit()
        got = get_earliest_cached_timestamp("ethusdt", "4H", db)
        assert got == t1
        assert got.tzinfo is not None


def test_lookback_start_time_subtracts_configured_days():
    fixed = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    with patch.object(candle_store, "_lookback_days", return_value=30.0):
        start = lookback_start_time("1h", now=fixed)
        assert start == fixed - timedelta(days=30)


@patch("src.cache.candle_store._fetch_live_candles")
def test_refresh_candles_force_full_uses_full_lookback_fetch(mock_fetch):
    mock_fetch.return_value = [
        Candle(
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            volume=0.0,
        )
    ]
    Session = _memory_session()
    now = datetime.now(timezone.utc)
    t_recent = now.replace(microsecond=0)
    with Session() as db:
        db.add(
            CandleCache(
                symbol="BTCUSDT",
                timeframe="1h",
                timestamp=t_recent,
                open=1.0,
                high=2.0,
                low=0.5,
                close=1.5,
                volume=100.0,
                updated_at=now,
            )
        )
        db.commit()
        n = refresh_candles("BTCUSDT", "1h", db, force_full=True)
        assert n == 1
    mock_fetch.assert_called_once()
    _args, kwargs = mock_fetch.call_args
    assert kwargs.get("start_time") is None
