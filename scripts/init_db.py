from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db.models import AlertZone, MonitoredSetup
from src.db.session import SessionLocal, init_db


def main() -> None:
    init_db()

    with SessionLocal() as db:
        db.query(AlertZone).delete()
        db.query(MonitoredSetup).delete()

        setup = MonitoredSetup(
            symbol="BTCUSDT",
            htf_timeframe="1h",
            htf_trend_direction="down",
            trend_score=0.0,
            structural_state_json={
                "walkable": True,
                "max_depth_reached": 1,
                "waiting_for": "mock-state",
                "levels": [],
            },
            last_checked_at=datetime.now(timezone.utc),
        )
        db.add(setup)
        db.flush()

        zone = AlertZone(
            setup_id=setup.id,
            zone_type="DEPTH_CHOCH",
            depth=1,
            price_high=73199.0,
            price_low=72270.41,
            is_active=True,
            watch_condition="price_enters_zone",
            is_manual_override=False,
        )
        db.add(zone)
        db.commit()


if __name__ == "__main__":
    main()
