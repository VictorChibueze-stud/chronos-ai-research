from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import AlertZone, MonitoredSetup
from src.db.session import Base
from src.ui.dashboard import build_zone_map_figure
from src.ui.data_access import add_manual_override, drop_setup, get_all_setups


def _build_memory_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session


def _sample_structural_state() -> dict:
    return {
        "walkable": True,
        "total_mitigation_count": 2,
        "max_depth_reached": 2,
        "waiting_for": "Depth 2 BOS confirmation",
        "levels": [
            {
                "depth": 1,
                "slice_start": 100,
                "slice_end": 190,
                "first_impulse_global_start": 110,
                "first_impulse_global_end": 140,
                "structural_level": {"price": 72271.41},
                "choch_zone": {
                    "lower_boundary": 64500.0,
                    "upper_boundary": 66826.5,
                },
            },
            {
                "depth": 2,
                "slice_start": 160,
                "slice_end": 230,
                "first_impulse_global_start": 175,
                "first_impulse_global_end": 205,
                "structural_level": {"price": 74050.0},
                "choch_zone": {
                    "lower_boundary": 69988.83,
                    "upper_boundary": 73199.0,
                },
            },
        ],
    }


def _new_setup(symbol: str, status: str = "SCANNING") -> MonitoredSetup:
    return MonitoredSetup(
        symbol=symbol,
        htf_timeframe="1h",
        htf_trend_direction="down",
        status=status,
        trend_score=0.87,
        structural_state_json=_sample_structural_state(),
        last_checked_at=datetime.now(timezone.utc),
    )


def test_get_all_setups_returns_dataframe_with_mapped_states():
    Session = _build_memory_session()

    with Session() as db:
        refining = _new_setup("BTCUSDT")
        in_trade = _new_setup("ETHUSDT", status="IN_TRADE")
        db.add_all([refining, in_trade])
        db.flush()
        db.add(
            AlertZone(
                setup_id=refining.id,
                zone_type="DEPTH_CHOCH",
                depth=2,
                price_high=73199.0,
                price_low=72270.41,
                watch_condition="price_enters_zone",
                is_active=True,
            )
        )
        db.commit()

        setups = get_all_setups(db)

        btc_row = setups.loc[setups["symbol"] == "BTCUSDT"].iloc[0]
        eth_row = setups.loc[setups["symbol"] == "ETHUSDT"].iloc[0]

        assert btc_row["state"] == "REFINING"
        assert btc_row["deepest_depth"] == 2
        assert btc_row["active_zone_low"] == 72270.41
        assert eth_row["state"] == "IN_TRADE"


def test_drop_setup_removes_setup_and_child_zones():
    Session = _build_memory_session()

    with Session() as db:
        setup = _new_setup("SOLUSDT")
        db.add(setup)
        db.flush()
        db.add(
            AlertZone(
                setup_id=setup.id,
                zone_type="DEPTH_CHOCH",
                depth=1,
                price_high=10.0,
                price_low=9.0,
                watch_condition="price_enters_zone",
                is_active=True,
            )
        )
        db.commit()

        assert drop_setup(db, setup.id) is True
        assert db.query(MonitoredSetup).count() == 0
        assert db.query(AlertZone).count() == 0


def test_add_manual_override_creates_override_zone_for_symbol():
    Session = _build_memory_session()

    with Session() as db:
        setup = _new_setup("BTCUSDT")
        db.add(setup)
        db.commit()

        zone = add_manual_override(
            db,
            symbol="BTCUSDT",
            zone_type="MANUAL_OVERRIDE",
            price_high=73100.0,
            price_low=72800.0,
            depth=3,
        )

        assert zone.setup_id == setup.id
        assert zone.is_manual_override is True
        assert zone.is_active is True
        assert zone.watch_condition == "price_enters_zone"


def test_build_zone_map_figure_draws_choch_and_bos_layers():
    figure = build_zone_map_figure(
        _sample_structural_state(),
        symbol="BTCUSDT",
        timeframe="1h",
    )

    names = [trace.name for trace in figure.data]

    assert "Depth 1 CHoCH" in names
    assert "Depth 1 BOS" in names
    assert "Depth 2 CHoCH" in names
    assert "Depth 2 BOS" in names
    assert figure.layout.title.text == "BTCUSDT 1h - Zone Map"