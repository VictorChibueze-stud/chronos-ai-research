from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import AlertZone, MonitoredSetup, SystemSettings, UniverseScore
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
        health_body = health_response.json()
        assert health_body["status"] == "online"
        assert health_body["active_setups"] == 1
        assert health_body["max_capacity"] == 50
        assert "last_scan" in health_body
        assert "next_scan" in health_body
        assert "scan_in_progress" in health_body

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

        with patch(
            "src.api.routers.setups._bootstrap_stage1_symbol",
            return_value=None,
        ):
            missing_response = client.get("/api/setups/BTCUSDT")
        assert missing_response.status_code == 200
        missing_body = missing_response.json()
        assert missing_body["symbol"] == "BTCUSDT"
        assert missing_body.get("readiness_state") == "ERROR"
    finally:
        app.dependency_overrides.clear()


def test_setups_list_includes_universe_rank_from_scores():
    Session = _build_memory_session()
    now = datetime.now(timezone.utc)
    with Session() as db:
        db.add(_new_setup("BTCUSDT"))
        db.add(
            UniverseScore(
                symbol="BTCUSDT",
                timeframe_basis="daily",
                trend_direction="up",
                confirmed_leg_count=2,
                leg_structure_json=[],
                impulse_price_ratio=1.0,
                impulse_velocity_ratio=1.0,
                retracement_phase_bonus=0.0,
                candidate_impulse_bonus=0.0,
                total_score=88.0,
                universe_rank=7,
                last_computed_at=now,
            )
        )
        db.commit()

    client, app = _create_client(Session)
    try:
        list_response = client.get("/api/setups")
        assert list_response.status_code == 200
        rows = list_response.json()
        btc = next(r for r in rows if r["symbol"] == "BTCUSDT")
        assert btc.get("universe_rank") == 7
        assert btc.get("timeframe_basis") == "daily"
    finally:
        app.dependency_overrides.clear()


def test_setups_scan_upserts_and_returns_all_setups():
    """POST /api/setups/scan must upsert a real result and return the full setup list."""
    from unittest.mock import MagicMock, patch

    # Run background threads synchronously so in_progress is reset before the next call.
    class _SyncThread:
        def __init__(self, target, args=(), kwargs=None, daemon=False):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}
        def start(self):
            self._target(*self._args, **self._kwargs)

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
            patch("src.api.routers.setups.threading.Thread", _SyncThread),
        ):
            scan_response = client.post(
                "/api/setups/scan",
                json={"symbols": ["BTCUSDT"], "timeframe": "1h"},
            )

        assert scan_response.status_code == 200
        payload = scan_response.json()
        assert isinstance(payload, dict)
        assert payload.get("status") == "scan_started"
        assert "total_symbols" in payload

        # Second call with same symbol+timeframe must still return scan_started
        with (
            patch("src.api.routers.setups.fetch_binance_ohlc_sync", return_value=[fake_candle] * 20),
            patch("src.api.routers.setups.identify_trend", return_value={**fake_identify_result, "current_phase": "impulse"}),
            patch("src.api.routers.setups.compute_internal_structure", return_value=[]),
            patch("src.api.routers.setups.walk_structure", return_value=fake_state_report),
            patch("src.api.routers.setups.serialize_state_report", return_value=fake_serialized),
            patch("src.api.routers.setups.threading.Thread", _SyncThread),
        ):
            scan_response2 = client.post(
                "/api/setups/scan",
                json={"symbols": ["BTCUSDT"], "timeframe": "1h"},
            )

        assert scan_response2.status_code == 200
        payload2 = scan_response2.json()
        assert isinstance(payload2, dict)
        assert payload2.get("status") == "scan_started"

        analysis_response = client.get("/api/analysis/BTCUSDT", params={"timeframe": "1h"})
        assert analysis_response.status_code == 200
        assert analysis_response.json()["symbol"] == "BTCUSDT"
    finally:
        app.dependency_overrides.clear()


def test_get_analysis_rejects_invalid_trend_query_params():
    Session = _build_memory_session()
    client, app = _create_client(Session)
    try:
        bad = client.get("/api/analysis/BTCUSDT", params={"min_swing_candles": "99"})
        assert bad.status_code == 422
        bad2 = client.get("/api/analysis/BTCUSDT", params={"trend_confirmation_pct": "0.6"})
        assert bad2.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_get_analysis_merges_optional_trend_query_params_into_identify_trend():
    Session = _build_memory_session()
    with Session() as db:
        db.add(_new_setup("BTCUSDT"))
        db.commit()

    client, app = _create_client(Session)

    fake_candle = MagicMock()
    fake_candle.timestamp = datetime.now(timezone.utc)
    fake_candle.open = fake_candle.high = fake_candle.low = fake_candle.close = 1.0

    captured: dict[str, Any] = {}

    def fake_identify(_candles, **kw: Any) -> dict[str, Any]:
        captured.clear()
        captured.update(kw)
        return {
            "trend": "up",
            "current_phase": "retracement",
            "legs": [{"type": "impulse", "confirmed": True, "start_index": 0, "end_index": 5}],
        }

    fake_state_report = {
        "walkable": True,
        "max_depth_reached": 1,
        "total_mitigation_count": 0,
        "levels": [],
        "global_trend": "up",
        "deepest_termination_reason": "max_depth_reached",
        "active_level": 1,
        "waiting_for": "",
        "stars_aligned": False,
        "reason": None,
    }

    try:
        with (
            patch(
                "src.api.routers.analysis.fetch_binance_ohlc_sync",
                return_value=[fake_candle] * 30,
            ),
            patch("src.api.routers.analysis.identify_trend", side_effect=fake_identify),
            patch("src.api.routers.analysis.compute_internal_structure"),
            patch("src.api.routers.analysis._enrich_internal_structure_with_tf_deepening"),
            patch("src.api.routers.analysis.compute_internal_structure_levels"),
            patch("src.api.routers.analysis.walk_structure", return_value=fake_state_report),
            patch("src.api.routers.analysis._compute_new_move_analysis", return_value=None),
            patch(
                "src.api.routers.analysis._serialize_trend_legs_structure",
                return_value={"legs": []},
            ),
        ):
            response = client.get(
                "/api/analysis/BTCUSDT",
                params={
                    "timeframe": "1h",
                    "min_swing_candles": "7",
                    "use_momentum_filter": "false",
                },
            )
        assert response.status_code == 200
        assert captured.get("min_swing_candles") == 7
        assert captured.get("use_momentum_filter") is False
        assert captured.get("use_dominance_filter") is True
    finally:
        app.dependency_overrides.clear()


def test_scan_with_empty_body_triggers_universe_discovery():
    from unittest.mock import MagicMock, patch
    from src.api.routers.setups import _scan_status as _global_scan_status
    _global_scan_status["in_progress"] = False

    # Run background threads synchronously so fetch_top_symbols is called before the assertions.
    class _SyncThread:
        def __init__(self, target, args=(), kwargs=None, daemon=False):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}
        def start(self):
            self._target(*self._args, **self._kwargs)

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
            # fetch_top_symbols is imported into setups via `from ... import`, so patch the local binding.
            patch("src.api.routers.setups.fetch_top_symbols", return_value=["BTCUSDT", "ETHUSDT"]) as mock_top,
            patch("src.adapters.deriv_data.get_active_deriv_symbols", return_value=["R_10"]) as mock_deriv,
            patch("src.api.routers.setups.fetch_binance_ohlc_sync", return_value=[fake_candle] * 20),
            patch("src.api.routers.setups.identify_trend", return_value=fake_identify_result),
            patch("src.api.routers.setups.compute_internal_structure", return_value=[]),
            patch("src.api.routers.setups.walk_structure", return_value=fake_state_report),
            patch("src.api.routers.setups.serialize_state_report", return_value=fake_serialized),
            patch("src.api.routers.setups.compute_correlation_groups", side_effect=lambda df, m: df),
            patch("src.api.routers.setups.threading.Thread", _SyncThread),
        ):
            scan_response = client.post("/api/setups/scan", json={})

        assert scan_response.status_code == 200
        payload = scan_response.json()
        assert isinstance(payload, dict)
        assert payload.get("status") == "scan_started"
        assert "total_symbols" in payload

        mock_top.assert_called_once_with(n=350)
        mock_deriv.assert_called_once_with()
    finally:
        app.dependency_overrides.clear()


def test_correlation_filter_removes_duplicates():
    """Stage 3 must remove correlated duplicates when explicitly enabled."""
    from unittest.mock import MagicMock, patch
    from src.api.routers.setups import ScanRequest, _run_scan_sync

    Session = _build_memory_session()

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
    fake_data = {
        "candles": [fake_candle] * 20,
        "result": fake_identify_result,
        "mtf_alignment": {"1h": "up"},
    }

    # Mock compute_correlation_groups to return only 2 out of 3 symbols
    def mock_correlation_groups(scan_df, symbol_candle_map):
        # Return DataFrame with only BTCUSDT and ETHUSDT (filter out R_10)
        filtered = scan_df[scan_df["symbol"].isin(["BTCUSDT", "ETHUSDT"])].copy()
        return filtered.reset_index(drop=True)

    with (
        patch("src.api.routers.setups.SessionLocal", Session),
        patch("src.api.routers.setups._stage1_binance_single", return_value=fake_data),
        patch("src.api.routers.setups._process_deriv_symbol", return_value=("R_10", fake_data)),
        patch("src.api.routers.setups.walk_structure", return_value=fake_state_report),
        patch("src.api.routers.setups.serialize_state_report", return_value=fake_serialized),
        patch("src.api.routers.setups.compute_correlation_groups", side_effect=mock_correlation_groups),
    ):
        _run_scan_sync(
            ScanRequest(
                symbols=["BTCUSDT", "ETHUSDT", "R_10"],
                timeframe="1h",
            ),
            settings={"enable_correlation_filter": True},
        )

    with Session() as db:
        symbols = {row.symbol for row in db.query(MonitoredSetup).all()}
    assert symbols == {"BTCUSDT", "ETHUSDT"}


def test_scan_settings_default_disables_correlation_filter():
    Session = _build_memory_session()
    client, app = _create_client(Session)

    try:
        response = client.get("/api/setups/scan-settings")
        assert response.status_code == 200
        payload = response.json()
        assert payload["enable_correlation_filter"] is False
        assert payload["universe_scan_frequency"] == "daily"
        assert payload["active_refresh_hours"] == 4
        cms = payload["category_min_slots"]
        assert cms["forex"] == 5
        assert cms["commodity"] == 3
        assert cms["indices"] == 3
        assert cms["synthetic"] == 5
        assert cms["crypto"] == 0
    finally:
        app.dependency_overrides.clear()


def test_run_scan_sync_stage1_writes_disable_evict():
    from src.api.routers.setups import ScanRequest, _run_scan_sync

    Session = _build_memory_session()
    fake_candle = MagicMock()
    fake_candle.timestamp = datetime.now(timezone.utc)
    fake_identify_result = {
        "trend": "up",
        "current_phase": "impulse",
        "legs": [],
    }
    fake_data = {
        "candles": [fake_candle] * 20,
        "result": fake_identify_result,
        "mtf_alignment": {"1h": "up"},
    }
    captured_evict_flags: list[bool] = []

    def _capture_write(_symbol, _data, _tf, _db, *, evict=True):
        captured_evict_flags.append(bool(evict))

    with (
        patch("src.api.routers.setups.SessionLocal", Session),
        patch("src.api.routers.setups._evict_to_capacity", return_value=None),
        patch("src.api.routers.setups._build_scan_symbol_universe", return_value=(["BTCUSDT", "R_10"], {"R_10"})),
        patch("src.api.routers.setups._stage1_binance_single", return_value=fake_data),
        patch("src.api.routers.setups._process_deriv_symbol", return_value=("R_10", fake_data)),
        patch("src.api.routers.setups._write_stage1_result", side_effect=_capture_write),
    ):
        _run_scan_sync(ScanRequest(symbols=[], timeframe="1h"))

    assert captured_evict_flags == [False, False]


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
        assert "last_error" in payload
    finally:
        app.dependency_overrides.clear()


def test_evict_to_capacity_keeps_manual_override_protected_rows():
    from src.api.routers.setups import _evict_to_capacity

    Session = _build_memory_session()
    with Session() as db:
        high = _new_setup("BTCUSDT")
        high.trend_score = 90.0
        low_protected = _new_setup("ETHUSDT")
        low_protected.trend_score = 1.0
        low_unprotected = _new_setup("SOLUSDT")
        low_unprotected.trend_score = 0.5
        db.add_all([high, low_protected, low_unprotected])
        db.commit()

        db.add(
            AlertZone(
                setup_id=low_protected.id,
                zone_type="MANUAL_OVERRIDE",
                depth=1,
                price_high=100.0,
                price_low=90.0,
                is_active=True,
                watch_condition="inside_zone",
                is_manual_override=True,
            )
        )
        db.commit()

        _evict_to_capacity(db, capacity=1)

        symbols = {row.symbol for row in db.query(MonitoredSetup).all()}
        assert "BTCUSDT" in symbols
        assert "ETHUSDT" in symbols  # protected from eviction
        assert "SOLUSDT" not in symbols


def test_run_scan_sync_sets_last_error_on_failure():
    from src.api.routers.setups import ScanRequest, _run_scan_sync, _scan_status

    Session = _build_memory_session()
    _scan_status.update(
        {
            "in_progress": False,
            "stage": None,
            "total_symbols": 0,
            "stage1_complete": 0,
            "stage2_complete": 0,
            "stage2_total": 0,
            "started_at": None,
            "completed_at": None,
            "last_error": None,
        }
    )

    with patch("src.api.routers.setups.SessionLocal", Session), patch(
        "src.api.routers.setups._evict_to_capacity",
        side_effect=RuntimeError("forced scan failure"),
    ):
        _run_scan_sync(ScanRequest(symbols=["BTCUSDT"], timeframe="1h"))

    assert _scan_status["stage"] == "failed"
    assert _scan_status["in_progress"] is False
    assert isinstance(_scan_status.get("last_error"), str)
    assert "forced scan failure" in str(_scan_status["last_error"])


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


def test_execution_status_endpoint():
    Session = _build_memory_session()
    client, app = _create_client(Session)
    try:
        response = client.get("/api/execution/status")
        assert response.status_code == 200
        body = response.json()
        assert "execution_enabled" in body
        assert "execution_paper_only" in body
        assert "execution_provider" in body
    finally:
        app.dependency_overrides.clear()