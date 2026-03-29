from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import AlertZone, MonitoredSetup
from src.db.session import Base
from src.orchestrator.fsm import SetupFSM
from src.orchestrator.manager import SetupManager


def _build_memory_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session


def _new_setup(symbol: str, score: float) -> MonitoredSetup:
    return MonitoredSetup(
        symbol=symbol,
        htf_timeframe="1h",
        htf_trend_direction="up",
        trend_score=score,
        structural_state_json={"walkable": True},
        last_checked_at=datetime.now(timezone.utc),
    )


def test_fsm_valid_lifecycle_path():
    fsm = SetupFSM()

    assert fsm.state == "SCANNING"

    fsm.on_zone_touched()
    assert fsm.state == "MONITORING"

    fsm.on_confirmation()
    assert fsm.state == "IN_TRADE"

    fsm.on_expiry()
    assert fsm.state == "EXPIRED"



def test_fsm_invalidation_and_reset_scan():
    fsm = SetupFSM()

    fsm.on_zone_touched()
    assert fsm.state == "MONITORING"

    fsm.on_invalidation()
    assert fsm.state == "INVALID"

    fsm.reset_scan()
    assert fsm.state == "SCANNING"



def test_manager_adds_new_setup_when_under_capacity():
    Session = _build_memory_session()

    with Session() as db:
        manager = SetupManager(db, max_setups=50)

        setup = manager.add_or_update_setup(
            symbol="BTCUSDT",
            htf_timeframe="1h",
            htf_trend_direction="up",
            trend_score=0.81,
            structural_state_json={"depth": 2},
        )

        assert setup is not None
        assert setup.symbol == "BTCUSDT"
        assert setup.status == "SCANNING"
        assert db.query(MonitoredSetup).count() == 1



def test_manager_updates_existing_setup_instead_of_adding_duplicate():
    Session = _build_memory_session()

    with Session() as db:
        manager = SetupManager(db, max_setups=50)

        created = manager.add_or_update_setup(
            symbol="ETHUSDT",
            htf_timeframe="4h",
            htf_trend_direction="up",
            trend_score=0.6,
            structural_state_json={"depth": 1},
        )

        updated = manager.add_or_update_setup(
            symbol="ETHUSDT",
            htf_timeframe="4h",
            htf_trend_direction="down",
            trend_score=0.92,
            structural_state_json={"depth": 3},
        )

        assert created.id == updated.id
        assert updated.htf_trend_direction == "down"
        assert updated.trend_score == 0.92
        assert updated.structural_state_json["depth"] == 3
        assert db.query(MonitoredSetup).count() == 1



def test_manager_evicts_lowest_trend_score_when_capacity_reached():
    Session = _build_memory_session()

    with Session() as db:
        for i in range(50):
            db.add(_new_setup(symbol=f"S{i}", score=0.5 + i / 1000))
        db.commit()

        low = db.query(MonitoredSetup).filter_by(symbol="S0").one()
        low.trend_score = 0.01
        db.commit()

        manager = SetupManager(db, max_setups=50)
        manager.add_or_update_setup(
            symbol="NEW_SYMBOL",
            htf_timeframe="1h",
            htf_trend_direction="up",
            trend_score=0.99,
            structural_state_json={"depth": 2},
        )

        symbols = {row.symbol for row in db.query(MonitoredSetup).all()}
        assert "S0" not in symbols
        assert "NEW_SYMBOL" in symbols
        assert len(symbols) == 50



def test_manager_does_not_evict_manual_override_setup():
    Session = _build_memory_session()

    with Session() as db:
        for i in range(50):
            setup = _new_setup(symbol=f"P{i}", score=0.2 + i / 1000)
            db.add(setup)
            db.flush()
            db.add(
                AlertZone(
                    setup_id=setup.id,
                    zone_type="DEPTH_CHOCH",
                    depth=2,
                    price_high=100.0,
                    price_low=90.0,
                    watch_condition="price_enters_zone",
                    is_active=True,
                    is_manual_override=True,
                )
            )
        db.commit()

        manager = SetupManager(db, max_setups=50)
        result = manager.add_or_update_setup(
            symbol="BLOCKED",
            htf_timeframe="1h",
            htf_trend_direction="up",
            trend_score=0.95,
            structural_state_json={"depth": 2},
        )

        assert result is None
        assert db.query(MonitoredSetup).count() == 50
        assert db.query(MonitoredSetup).filter_by(symbol="BLOCKED").count() == 0
