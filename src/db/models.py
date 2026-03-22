from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.session import Base


class MonitoredSetup(Base):
    __tablename__ = "monitored_setups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    htf_timeframe: Mapped[str] = mapped_column(String)
    htf_trend_direction: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="SCANNING")
    trend_score: Mapped[float] = mapped_column(Float)
    structural_state_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    alert_zones: Mapped[list["AlertZone"]] = relationship(
        back_populates="setup", cascade="all, delete-orphan"
    )


class AlertZone(Base):
    __tablename__ = "alert_zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    setup_id: Mapped[int] = mapped_column(Integer, ForeignKey("monitored_setups.id"))
    zone_type: Mapped[str] = mapped_column(String)
    depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_high: Mapped[float] = mapped_column(Float)
    price_low: Mapped[float] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    watch_condition: Mapped[str] = mapped_column(String)
    is_manual_override: Mapped[bool] = mapped_column(Boolean, default=False)

    setup: Mapped[MonitoredSetup] = relationship(back_populates="alert_zones")
