"""Tests for apply_scan_schedule_from_db and POST /api/scanner/apply-schedule."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.session import Base


def _build_memory_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_apply_scan_schedule_graceful_when_scheduler_not_running():
    from src.api.main import apply_scan_schedule_from_db

    Session = _build_memory_session()
    db = Session()
    try:
        out = apply_scan_schedule_from_db(db)
    finally:
        db.close()
    assert out["ok"] is False
    assert out["reason"] == "scheduler not running"
    assert out["jobs"] == []


def test_post_apply_schedule_with_running_app():
    from src.api.main import app, get_db

    Session = _build_memory_session()

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            r = client.post("/api/scanner/apply-schedule")
            assert r.status_code == 200
            body = r.json()
            assert body["ok"] is True
            assert len(body["jobs"]) == 6
            ids = {j["job_id"] for j in body["jobs"]}
            assert ids == {
                "rank_multi_asset",
                "refresh_multi_asset",
                "rank_synthetic",
                "refresh_synthetic",
                "rank_crypto",
                "refresh_crypto",
            }
    finally:
        app.dependency_overrides.clear()
