from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
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


class UniverseSettings(Base):
    __tablename__ = "universe_settings"
    __table_args__ = (
        UniqueConstraint(
            "universe_name",
            name="uq_universe_settings_name",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    universe_name: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )
    capacity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=50
    )
    rank_frequency: Mapped[str] = mapped_column(
        String, nullable=False, default="weekly"
    )
    refresh_offset_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    refresh_interval_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=4
    )
    top_n: Mapped[int] = mapped_column(
        Integer, nullable=False, default=350
    )
    non_top_n_depth: Mapped[str] = mapped_column(
        String, nullable=False, default="global_and_prime"
    )
    category_min_slots_json: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class MonitoredSetup(Base):
    __tablename__ = "monitored_setups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    universe: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None, index=True
    )
    htf_timeframe: Mapped[str] = mapped_column(String)
    htf_trend_direction: Mapped[str] = mapped_column(String)
    current_phase: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="SCANNING")
    ema_signal: Mapped[Optional[str]] = mapped_column(String, nullable=True, default=None)
    trend_score: Mapped[float] = mapped_column(Float)
    structural_state_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    mtf_alignment: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=True)
    candidate_ichoch_reached: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, default=None)
    new_move_active: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, default=None)
    normalised_distance_to_bos: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=None)
    market_state: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )
    critical_veto_flag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # When fundamentals analysis last ran for this market.
    fundamental_analyzed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
    universe_name: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )


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
    market_state: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )


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


class CandidateImpulseCache(Base):
    """Cached candidate impulse analysis from tested CHoCH zone to current price."""

    __tablename__ = "candidate_impulse_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    source_timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    start_price: Mapped[float] = mapped_column(Float, nullable=False)
    start_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    choch_source: Mapped[str] = mapped_column(String(20), nullable=False)
    legs_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    bos_levels_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    choch_zone_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    prime_impulse_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    prime_choch_zone_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    structure_broken: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    candidate_walker_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SymbolAnalysisParams(Base):
    """Per-symbol analysis parameter overrides for identify_trend and related scanners."""

    __tablename__ = "symbol_analysis_params"
    __table_args__ = (UniqueConstraint("symbol", name="uq_symbol_analysis_params_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    params_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ManualStructureOverride(Base):
    __tablename__ = "manual_structure_overrides"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "override_type", "depth_index",
            name="uq_manual_override_symbol_type_depth",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True,
    )
    symbol: Mapped[str] = mapped_column(
        String, nullable=False, index=True,
    )
    override_type: Mapped[str] = mapped_column(
        String, nullable=False,
    )
    # Valid values:
    # "trend_bounds"        — trend start/end dates
    # "global_choch"        — global CHoCH zone price range
    # "ichoch"              — internal CHoCH (prime impulse)
    # "depth_choch"         — walker depth CHoCH zone
    # "candidate_choch"     — candidate impulse CHoCH
    # "candidate_ichoch"    — candidate internal CHoCH

    lower_boundary: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
    )
    upper_boundary: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
    )

    approx_price_a: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
    )
    approx_timestamp_a: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    approx_price_b: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
    )
    approx_timestamp_b: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    start_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    end_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    trend_start_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    trend_end_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    depth_index: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
    )

    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )

    notes: Mapped[Optional[str]] = mapped_column(
        String, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    reset_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )


class MarketStateHistory(Base):
    __tablename__ = "market_state_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    state: Mapped[str] = mapped_column(String, nullable=False)
    previous_state: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    transitioned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trend_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class ContractSpec(Base):
    __tablename__ = "contract_specs"
    __table_args__ = (
        UniqueConstraint("symbol", name="uq_contract_specs_symbol"),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    symbol: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )
    asset_class: Mapped[str] = mapped_column(
        String, nullable=False
    )

    pip_size: Mapped[float] = mapped_column(Float, nullable=False)
    point_value: Mapped[float] = mapped_column(Float, nullable=False)
    contract_size: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0
    )

    lot_size_min: Mapped[float] = mapped_column(Float, nullable=False)
    lot_size_max: Mapped[float] = mapped_column(Float, nullable=False)
    lot_size_step: Mapped[float] = mapped_column(Float, nullable=False)

    quote_currency: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    base_currency: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )

    is_crypto: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    notes: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )

    last_fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class PaperAccount(Base):
    __tablename__ = "paper_accounts"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(
        String, nullable=False, unique=True
    )
    account_type: Mapped[str] = mapped_column(
        String, nullable=False
    )
    balance_usd: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    initial_balance_usd: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    drawdown_limit_pct: Mapped[float] = mapped_column(
        Float, nullable=False, default=20.0
    )
    risk_per_trade_pct: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.25
    )
    max_concurrent_positions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5
    )
    scale_by_score: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    entry_ema_fast: Mapped[int] = mapped_column(
        Integer, nullable=False, default=9
    )
    entry_ema_slow: Mapped[int] = mapped_column(
        Integer, nullable=False, default=21
    )
    entry_timeframe: Mapped[str] = mapped_column(
        String, nullable=False, default="15m"
    )
    min_market_state: Mapped[str] = mapped_column(
        String, nullable=False, default="CANDIDATE_ACTIVE"
    )
    tp_mode: Mapped[str] = mapped_column(
        String, nullable=False, default="global_bos"
    )
    entry_lookback_candles: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    # How many of the most recent completed candles to
    # check for an EMA crossover. Default 3 means a
    # crossover on any of the last 3 candles still counts.
    entry_check_interval_hours: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0
    )
    # How often (in hours) the entry signal scheduler runs,
    # independently of the 4h structural refresh. Default 1.0.
    time_exit_days: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, default=None
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    is_paused_drawdown: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    universe: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )
    # "multi_asset" | "synthetic" | "crypto"
    # When set, account only trades symbols from
    # this universe.
    metric_targets_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None
    )
    # JSON-encoded performance metric targets for the
    # Risk page (display only, no trading impact).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    trades: Mapped[list["PaperTrade"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
    )


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("paper_accounts.id"),
        nullable=False,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )
    direction: Mapped[str] = mapped_column(
        String, nullable=False
    )

    entry_price: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    stop_price: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    take_profit_price: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    lot_size: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    risk_amount_usd: Mapped[float] = mapped_column(
        Float, nullable=False
    )

    market_state_at_entry: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    score_at_entry: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    entry_timeframe: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )

    status: Mapped[str] = mapped_column(
        String, nullable=False, default="open", index=True
    )
    open_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    close_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    close_price: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    pnl_usd: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    pnl_pct: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    max_adverse_excursion_usd: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    account: Mapped["PaperAccount"] = relationship(
        back_populates="trades"
    )


class AnalysisResultCache(Base):
    """Cache of the full ``GET /api/analysis/{symbol}`` response.

    Rows are written by the 4-hour refresh job (and the live request that
    produces the first miss) and invalidated by:
      * ``run_universe_ranking`` after promoting a symbol
      * manual structure override POSTs
      * TTL expiry (default 4 hours)
      * params-hash mismatch (scan settings changed)
    """

    __tablename__ = "analysis_result_cache"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "timeframe",
            name="uq_analysis_cache_sym_tf",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    symbol: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )
    timeframe: Mapped[str] = mapped_column(
        String, nullable=False
    )
    result_json: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    params_hash: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    ttl_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=14400
    )
