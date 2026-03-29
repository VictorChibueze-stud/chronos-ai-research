from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from src.db.models import AlertZone, MonitoredSetup, SystemSettings
from src.db.session import Base


def _build_memory_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return engine, Session


def test_db_tables_can_be_created():
    engine, _ = _build_memory_session()
    inspector = inspect(engine)

    tables = set(inspector.get_table_names())
    assert "monitored_setups" in tables
    assert "alert_zones" in tables
    assert "system_settings" in tables


def test_insert_and_query_system_settings_defaults_to_inactive():
    _, Session = _build_memory_session()

    with Session() as db:
        settings = SystemSettings()
        db.add(settings)
        db.commit()

    with Session() as db:
        saved = db.query(SystemSettings).one()
        assert saved.killswitch_active is False


def test_insert_and_query_setup_with_alert_zone():
    _, Session = _build_memory_session()

    structural_state = {
        "walkable": True,
        "max_depth_reached": 2,
        "waiting_for": "Depth 2 CHoCH zone test",
        "levels": [
            {
                "depth": 2,
                "structural_level": {"price": 74050.0},
            }
        ],
    }

    with Session() as db:
        setup = MonitoredSetup(
            symbol="BTCUSDT",
            htf_timeframe="1h",
            htf_trend_direction="down",
            trend_score=0.72,
            structural_state_json=structural_state,
            last_checked_at=datetime.now(timezone.utc),
        )
        db.add(setup)
        db.flush()

        zone = AlertZone(
            setup_id=setup.id,
            zone_type="DEPTH_CHOCH",
            depth=2,
            price_high=73199.0,
            price_low=72270.41,
            watch_condition="price_enters_zone",
        )
        db.add(zone)
        db.commit()

    with Session() as db:
        saved_setup = db.query(MonitoredSetup).filter_by(symbol="BTCUSDT").one()

        assert saved_setup.status == "SCANNING"
        assert saved_setup.structural_state_json["walkable"] is True
        assert saved_setup.structural_state_json["levels"][0]["depth"] == 2

        saved_zone = db.query(AlertZone).filter_by(setup_id=saved_setup.id).one()
        assert saved_zone.zone_type == "DEPTH_CHOCH"
        assert saved_zone.depth == 2
        assert saved_zone.is_active is True
        assert saved_zone.is_manual_override is False
