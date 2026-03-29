from datetime import datetime, timezone
from typing import Any

from sqlalchemy import exists
from sqlalchemy.orm import Session

from src.db.models import AlertZone, MonitoredSetup


class SetupManager:
    """Manage monitored setups with bounded memory and score-based eviction."""

    def __init__(self, db: Session, max_setups: int = 50) -> None:
        self.db = db
        self.max_setups = max_setups

    def add_or_update_setup(
        self,
        *,
        symbol: str,
        htf_timeframe: str,
        htf_trend_direction: str,
        trend_score: float,
        structural_state_json: dict[str, Any],
    ) -> MonitoredSetup | None:
        existing = (
            self.db.query(MonitoredSetup)
            .filter(
                MonitoredSetup.symbol == symbol,
                MonitoredSetup.htf_timeframe == htf_timeframe,
            )
            .one_or_none()
        )

        now = datetime.now(timezone.utc)
        if existing is not None:
            existing.htf_trend_direction = htf_trend_direction
            existing.trend_score = trend_score
            existing.structural_state_json = structural_state_json
            existing.last_checked_at = now
            self.db.commit()
            self.db.refresh(existing)
            return existing

        if self.db.query(MonitoredSetup).count() >= self.max_setups:
            evicted = self._evict_lowest_score_setup()
            if not evicted:
                return None

        setup = MonitoredSetup(
            symbol=symbol,
            htf_timeframe=htf_timeframe,
            htf_trend_direction=htf_trend_direction,
            trend_score=trend_score,
            structural_state_json=structural_state_json,
            last_checked_at=now,
            status="SCANNING",
        )
        self.db.add(setup)
        self.db.commit()
        self.db.refresh(setup)
        return setup

    def _evict_lowest_score_setup(self) -> bool:
        protected_exists = exists().where(
            AlertZone.setup_id == MonitoredSetup.id,
            AlertZone.is_active.is_(True),
            AlertZone.is_manual_override.is_(True),
        )

        candidate = (
            self.db.query(MonitoredSetup)
            .filter(~protected_exists)
            .order_by(MonitoredSetup.trend_score.asc(), MonitoredSetup.id.asc())
            .first()
        )
        if candidate is None:
            return False

        self.db.delete(candidate)
        self.db.commit()
        return True
