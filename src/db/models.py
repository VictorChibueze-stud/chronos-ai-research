from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.session import Base


class SystemSettings(Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    killswitch_active: Mapped[bool] = mapped_column(Boolean, default=False)


class ScanSettings(Base):
    __tablename__ = "scan_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True, default="global")
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ScanSettingsHistory(Base):
    __tablename__ = "scan_settings_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="global")
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )


class MonitoredSetup(Base):
    __tablename__ = "monitored_setups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    htf_timeframe: Mapped[str] = mapped_column(String)
    htf_trend_direction: Mapped[str] = mapped_column(String)
    current_phase: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="SCANNING")
    ema_signal: Mapped[Optional[str]] = mapped_column(String, nullable=True, default=None)
    trend_score: Mapped[float] = mapped_column(Float)
    structural_state_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    mtf_alignment: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=True)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    alert_zones: Mapped[list["AlertZone"]] = relationship(
        back_populates="setup", cascade="all, delete-orphan"
    )

    def is_protected(self) -> bool:
        """Check if this setup is protected from eviction.
        
        A setup is protected if it has any active manual override zones.
        """
        for zone in self.alert_zones:
            if zone.is_manual_override and zone.is_active:
                return True
        return False


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


class CandleCache(Base):
    __tablename__ = "candle_cache"
    __table_args__ = (UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_candle_cache"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String, nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActiveUniverseSymbol(Base):
    __tablename__ = "active_universe_symbols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class UniverseBootstrapFailure(Base):
    """Recorded when on-demand stage-1 bootstrap fails (no setup row persisted)."""

    __tablename__ = "universe_bootstrap_failures"

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)


class SignalHistory(Base):
    __tablename__ = "signal_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String, nullable=False, index=True)
    signal: Mapped[str] = mapped_column(String, nullable=False)
    trend_direction: Mapped[str | None] = mapped_column(String, nullable=True)
    trend_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    emitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class ExecutionOrder(Base):
    __tablename__ = "execution_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    intent_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    provider_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    events: Mapped[list["ExecutionEvent"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class ExecutionEvent(Base):
    __tablename__ = "execution_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("execution_orders.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    order: Mapped["ExecutionOrder"] = relationship(back_populates="events")


class UniverseScore(Base):
    """One row per symbol; updated on each universe ranking run."""

    __tablename__ = "universe_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    timeframe_basis: Mapped[str] = mapped_column(String(16), nullable=False)
    trend_direction: Mapped[str] = mapped_column(String(16), nullable=False)
    confirmed_leg_count: Mapped[int] = mapped_column(Integer, nullable=False)
    leg_structure_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    impulse_price_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    impulse_velocity_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    retracement_phase_bonus: Mapped[float] = mapped_column(Float, nullable=False)
    candidate_impulse_bonus: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    universe_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    computation_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)


class ScanJobLog(Base):
    """Append-only log of ranking / refresh job executions."""

    __tablename__ = "scan_job_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_symbols: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)


class GlobalStructureCache(Base):
    """Cached global structure (e.g. daily/weekly reference) per symbol."""

    __tablename__ = "global_structure_cache"
    __table_args__ = (UniqueConstraint("symbol", name="uq_global_structure_cache_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    reference_timeframe: Mapped[str] = mapped_column(String, nullable=False)
    confirmed_leg_count: Mapped[int] = mapped_column(Integer, nullable=False)
    legs_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    bos_levels_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    choch_zone_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    choch_level_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    trend_direction: Mapped[str] = mapped_column(String, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    candle_start_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    candle_end_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PrimeImpulseStructure(Base):
    """Best internal zigzag on the last global impulse window (finer TF pick)."""

    __tablename__ = "prime_impulse_structure"
    __table_args__ = (UniqueConstraint("symbol", name="uq_prime_impulse_structure_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source_timeframe: Mapped[str] = mapped_column(String, nullable=False)
    confirmed_leg_count: Mapped[int] = mapped_column(Integer, nullable=False)
    legs_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    bos_levels_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    choch_zone_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    impulse_start_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    impulse_end_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    impulse_start_price: Mapped[float] = mapped_column(Float, nullable=False)
    impulse_end_price: Mapped[float] = mapped_column(Float, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StoredWalkerResult(Base):
    """One row per symbol: last structural walker state (JSON from serialize_state_report)."""

    __tablename__ = "stored_walker_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    source_timeframe: Mapped[str] = mapped_column(String, nullable=False)
    walker_state_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    max_depth_reached: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_mitigation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    waiting_for: Mapped[str | None] = mapped_column(String, nullable=True)
    global_choch_zone_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
