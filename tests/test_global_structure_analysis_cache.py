"""Tests for GlobalStructureCache-backed analysis leg remapping."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.routers.analysis import _remap_cached_legs_to_chart
from src.db.session import Base
from src.scanner.global_structure import compute_walker_for_symbol, get_stored_walker


def test_remap_cached_legs_preserves_prices_and_sets_chart_indices() -> None:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    chart = [SimpleNamespace(timestamp=base + timedelta(hours=i)) for i in range(100)]
    legs_json = [
        {
            "type": "impulse",
            "confirmed": True,
            "start_price": 1.0,
            "end_price": 2.0,
            "start_timestamp": (base + timedelta(hours=10)).isoformat(),
            "end_timestamp": (base + timedelta(hours=20)).isoformat(),
            "start_index": 0,
            "end_index": 5,
        }
    ]
    out = _remap_cached_legs_to_chart(legs_json, chart)
    assert len(out) == 1
    assert out[0]["start_price"] == 1.0
    assert out[0]["end_price"] == 2.0
    assert 0 <= out[0]["start_index"] <= out[0]["end_index"] < 100
    assert out[0]["start_index"] == 10
    assert out[0]["end_index"] == 20


def test_compute_walker_for_symbol_returns_none_without_prerequisites() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    assert compute_walker_for_symbol("BTCUSDT", db) is None
    assert get_stored_walker("BTCUSDT", db) is None
