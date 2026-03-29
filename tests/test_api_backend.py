from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import AlertZone, MonitoredSetup, SystemSettings
from src.db.session import Base


def _build_memory_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return Session


def _new_setup(symbol: str = "BTCUSDT") -> MonitoredSetup:
    return MonitoredSetup(
        symbol=symbol,
        htf_timeframe="1h",
        htf_trend_direction="up",
        status="SCANNING",
        trend_score=0.88,
        structural_state_json={
            "walkable": True,
            "max_depth_reached": 2,
            "levels": [{"depth": 2, "structural_level": {"price": 74050.0}}],
        },
        last_checked_at=datetime.now(timezone.utc),
    )


def _create_client(Session):
    from src.api.main import app
    from src.api.main import get_db

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    return client, app


def test_system_health_and_killswitch_endpoints():
    Session = _build_memory_session()

    with Session() as db:
        db.add(_new_setup("BTCUSDT"))
        db.commit()

    client, app = _create_client(Session)

    try:
        health_response = client.get("/api/system/health")
        assert health_response.status_code == 200
        assert health_response.json() == {
            "status": "online",
            "active_setups": 1,
            "max_capacity": 50,
        }

        initial_killswitch = client.get("/api/system/killswitch")
        assert initial_killswitch.status_code == 200
        assert initial_killswitch.json() == {"killswitch_active": False}

        toggle_response = client.post("/api/system/killswitch")
        assert toggle_response.status_code == 200
        assert toggle_response.json() == {"killswitch_active": True}

        with Session() as db:
            settings = db.query(SystemSettings).one()
            assert settings.killswitch_active is True
    finally:
        app.dependency_overrides.clear()


def test_setups_endpoints_return_and_delete_records():
    Session = _build_memory_session()

    with Session() as db:
        db.add_all([_new_setup("BTCUSDT"), _new_setup("ETHUSDT")])
        db.commit()

    client, app = _create_client(Session)

    try:
        list_response = client.get("/api/setups")
        assert list_response.status_code == 200
        payload = list_response.json()

        assert len(payload) == 2
        assert isinstance(payload[0]["structural_state"], dict)
        assert payload[0]["timeframe"] == "1h"
        assert payload[0]["trend"] == "up"
        assert payload[0]["fsm_state"] == "SCANNING"

        detail_response = client.get("/api/setups/BTCUSDT")
        assert detail_response.status_code == 200
        assert detail_response.json()["symbol"] == "BTCUSDT"

        delete_response = client.delete("/api/setups/BTCUSDT")
        assert delete_response.status_code == 200
        assert delete_response.json() == {"deleted": True, "symbol": "BTCUSDT"}

        missing_response = client.get("/api/setups/BTCUSDT")
        assert missing_response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_setups_scan_upserts_and_returns_all_setups():
    """POST /api/setups/scan must upsert a real result and return the full setup list."""
    from unittest.mock import MagicMock, patch

    Session = _build_memory_session()
    client, app = _create_client(Session)

    fake_candle = MagicMock()
    fake_candle.timestamp = datetime.now(timezone.utc)

    fake_identify_result = {
        "trend": "up",
        "current_phase": "retracement",
        "legs": [],
    }
    fake_state_report = {
        "walkable": True,
        "max_depth_reached": 2,
        "total_mitigation_count": 1,
        "levels": [],
        "global_trend": "up",
        "deepest_termination_reason": "max_depth_reached",
        "active_level": 1,
        "waiting_for": "",
        "stars_aligned": False,
        "reason": None,
    }
    fake_serialized = dict(fake_state_report)

    try:
        with (
            patch("src.api.routers.setups.fetch_binance_ohlc_sync", return_value=[fake_candle] * 20),
            patch("src.api.routers.setups.identify_trend", return_value=fake_identify_result),
            patch("src.api.routers.setups.compute_internal_structure", return_value=[]),
            patch("src.api.routers.setups.walk_structure", return_value=fake_state_report),
            patch("src.api.routers.setups.serialize_state_report", return_value=fake_serialized),
        ):
            scan_response = client.post(
                "/api/setups/scan",
                json={"symbols": ["BTCUSDT"], "timeframe": "1h"},
            )

        assert scan_response.status_code == 200
        payload = scan_response.json()
        assert isinstance(payload, list)
        assert len(payload) == 1
        row = payload[0]
        assert row["symbol"] == "BTCUSDT"
        assert row["timeframe"] == "1h"
        assert row["trend"] == "up"
        assert row["fsm_state"] == "MONITORING"
        # trend_score = max_depth_reached * 10 + total_mitigation_count * 5 = 2*10 + 1*5 = 25
        assert row["trend_score"] == 25.0
        assert isinstance(row["structural_state"], dict)

        # Second call with same symbol+timeframe must update, not create a duplicate
        with (
            patch("src.api.routers.setups.fetch_binance_ohlc_sync", return_value=[fake_candle] * 20),
            patch("src.api.routers.setups.identify_trend", return_value={**fake_identify_result, "current_phase": "impulse"}),
            patch("src.api.routers.setups.compute_internal_structure", return_value=[]),
            patch("src.api.routers.setups.walk_structure", return_value=fake_state_report),
            patch("src.api.routers.setups.serialize_state_report", return_value=fake_serialized),
        ):
            scan_response2 = client.post(
                "/api/setups/scan",
                json={"symbols": ["BTCUSDT"], "timeframe": "1h"},
            )

        assert scan_response2.status_code == 200
        payload2 = scan_response2.json()
        assert len(payload2) == 1  # still one row, not two
        assert payload2[0]["fsm_state"] == "SCANNING"

        analysis_response = client.get("/api/analysis/BTCUSDT", params={"timeframe": "1h"})
        assert analysis_response.status_code == 200
        assert analysis_response.json() == {
            "status": "analysis_pending",
            "symbol": "BTCUSDT",
        }
    finally:
        app.dependency_overrides.clear()


def test_scan_with_empty_body_triggers_universe_discovery():
    from unittest.mock import MagicMock, patch

    Session = _build_memory_session()
    client, app = _create_client(Session)

    fake_candle = MagicMock()
    fake_candle.timestamp = datetime.now(timezone.utc)

    fake_identify_result = {
        "trend": "up",
        "current_phase": "retracement",
        "legs": [],
    }
    fake_state_report = {
        "walkable": True,
        "max_depth_reached": 1,
        "total_mitigation_count": 1,
        "levels": [],
        "global_trend": "up",
        "deepest_termination_reason": "max_depth_reached",
        "active_level": 1,
        "waiting_for": "",
        "stars_aligned": False,
        "reason": None,
    }
    fake_serialized = dict(fake_state_report)

    try:
        with (
            patch("src.scanner.market_scanner.fetch_top_symbols", return_value=["BTCUSDT", "ETHUSDT"]) as mock_top,
            patch("src.adapters.deriv_data.get_active_deriv_symbols", return_value=["R_10"]) as mock_deriv,
            patch("src.api.routers.setups.fetch_binance_ohlc_sync", return_value=[fake_candle] * 20),
            patch("src.api.routers.setups.identify_trend", return_value=fake_identify_result),
            patch("src.api.routers.setups.compute_internal_structure", return_value=[]),
            patch("src.api.routers.setups.walk_structure", return_value=fake_state_report),
            patch("src.api.routers.setups.serialize_state_report", return_value=fake_serialized),
            patch("src.api.routers.setups.compute_correlation_groups", side_effect=lambda df, m: df),
        ):
            scan_response = client.post("/api/setups/scan", json={})

        assert scan_response.status_code == 200
        payload = scan_response.json()
        assert isinstance(payload, list)
        assert len(payload) == 3
        assert {row["symbol"] for row in payload} == {"BTCUSDT", "ETHUSDT", "R_10"}

        mock_top.assert_called_once_with(n=50)
        mock_deriv.assert_called_once_with()
    finally:
        app.dependency_overrides.clear()


def test_correlation_filter_removes_duplicates():
    """POST /api/setups/scan must remove correlated duplicates in Stage 3."""
    from unittest.mock import MagicMock, patch

    Session = _build_memory_session()
    client, app = _create_client(Session)

    fake_candle = MagicMock()
    fake_candle.timestamp = datetime.now(timezone.utc)

    fake_identify_result = {
        "trend": "up",
        "current_phase": "retracement",
        "legs": [],
    }
    fake_state_report = {
        "walkable": True,
        "max_depth_reached": 2,
        "total_mitigation_count": 1,
        "levels": [],
        "global_trend": "up",
        "deepest_termination_reason": "max_depth_reached",
        "active_level": 1,
        "waiting_for": "",
        "stars_aligned": False,
        "reason": None,
    }
    fake_serialized = dict(fake_state_report)

    try:
        # Mock compute_correlation_groups to return only 2 out of 3 symbols
        def mock_correlation_groups(scan_df, symbol_candle_map):
            # Return DataFrame with only BTCUSDT and ETHUSDT (filter out R_10)
            import pandas as pd
            filtered = scan_df[scan_df["symbol"].isin(["BTCUSDT", "ETHUSDT"])].copy()
            return filtered.reset_index(drop=True)

        with (
            patch("src.api.routers.setups.fetch_binance_ohlc_sync", return_value=[fake_candle] * 20),
            patch("src.api.routers.setups.identify_trend", return_value=fake_identify_result),
            patch("src.api.routers.setups.compute_internal_structure", return_value=[]),
            patch("src.api.routers.setups.walk_structure", return_value=fake_state_report),
            patch("src.api.routers.setups.serialize_state_report", return_value=fake_serialized),
            patch("src.api.routers.setups.compute_correlation_groups", side_effect=mock_correlation_groups),
        ):
            scan_response = client.post(
                "/api/setups/scan",
                json={"symbols": ["BTCUSDT", "ETHUSDT", "R_10"], "timeframe": "1h"},
            )

        assert scan_response.status_code == 200
        payload = scan_response.json()
        
        # Should only have 2 symbols (BTCUSDT and ETHUSDT), R_10 filtered out by correlation
        assert isinstance(payload, list)
        assert len(payload) == 2
        assert {row["symbol"] for row in payload} == {"BTCUSDT", "ETHUSDT"}
    finally:
        app.dependency_overrides.clear()


def test_scan_status_endpoint_returns_progress():
    Session = _build_memory_session()
    client, app = _create_client(Session)

    try:
        response = client.get("/api/system/scan-status")
        assert response.status_code == 200
        payload = response.json()
        assert "in_progress" in payload
        assert "stage1_complete" in payload
        assert "stage2_complete" in payload
    finally:
        app.dependency_overrides.clear()


def test_overrides_endpoints_create_list_and_delete_manual_override_zones():
    Session = _build_memory_session()

    with Session() as db:
        db.add(_new_setup("BTCUSDT"))
        db.commit()

    client, app = _create_client(Session)

    try:
        create_response = client.post(
            "/api/overrides",
            json={
                "symbol": "BTCUSDT",
                "zone_type": "MANUAL_OVERRIDE",
                "price_high": 73100.0,
                "price_low": 72800.0,
            },
        )
        assert create_response.status_code == 200
        created_zone = create_response.json()

        assert created_zone["symbol"] == "BTCUSDT"
        assert created_zone["is_manual_override"] is True

        list_response = client.get("/api/overrides")
        assert list_response.status_code == 200
        zones = list_response.json()
        assert len(zones) == 1
        assert zones[0]["zone_type"] == "MANUAL_OVERRIDE"

        delete_response = client.delete(f"/api/overrides/{created_zone['id']}")
        assert delete_response.status_code == 200
        assert delete_response.json() == {"deleted": True, "zone_id": created_zone["id"]}

        with Session() as db:
            assert db.query(AlertZone).count() == 0
    finally:
        app.dependency_overrides.clear()