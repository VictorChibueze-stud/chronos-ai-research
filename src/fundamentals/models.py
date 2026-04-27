from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.session import Base


class EconomicEvent(Base):
    __tablename__ = "economic_events"
    __table_args__ = (UniqueConstraint("event_name", "scheduled_at", name="uq_economic_event"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_name: Mapped[str] = mapped_column(String(255), nullable=False)
    event_category: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    impact_level: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    forecast_value: Mapped[str | None] = mapped_column(String(50), nullable=True)
    actual_value: Mapped[str | None] = mapped_column(String(50), nullable=True)
    previous_value: Mapped[str | None] = mapped_column(String(50), nullable=True)
    affected_markets: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    headline: Mapped[str] = mapped_column(String(500), nullable=False)
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    market_tags: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    event_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("economic_events.id"), nullable=True)
    fetch_snapshot: Mapped[str | None] = mapped_column(String(10), nullable=True)
    sentiment_label: Mapped[str] = mapped_column(String(20), nullable=False)
    sentiment_score: Mapped[float] = mapped_column(Float, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class FundamentalEventImpact(Base):
    __tablename__ = "fundamental_event_impact"
    __table_args__ = (UniqueConstraint("market_symbol", "event_category", name="uq_event_impact"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    event_category: Mapped[str] = mapped_column(String(100), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    median_shock_pct: Mapped[float] = mapped_column(Float, nullable=False)
    median_recovery_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EventImpactRanking(Base):
    __tablename__ = "event_impact_ranking"
    __table_args__ = (UniqueConstraint("market_symbol", "event_category", name="uq_impact_ranking"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    event_category: Mapped[str] = mapped_column(String(100), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    median_shock_pct: Mapped[float] = mapped_column(Float, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FundamentalStory(Base):
    """
    LLM-generated story clusters for a market.
    One row per symbol. Upserted daily.
    Stores the full structured intelligence
    payload including stories, actors,
    timeline, and veto assessment.
    """

    __tablename__ = "fundamental_stories"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            name="uq_fundamental_stories_symbol",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    symbol: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )
    # The prime impulse start date used as the
    # anchor for news and event window.
    prime_impulse_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Full structured JSON payload from LLM chain.
    # Contains: stories, actors, timeline,
    # upcoming_events, risk_summary.
    stories_json: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    critical_veto_flag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    veto_reason: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    veto_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Which LLM model answered the final call.
    model_used: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    # Window used for this analysis.
    news_window_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    news_window_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class FundamentalAnalysisLog(Base):
    """
    Log of each fundamentals analysis run.
    Records which markets were processed,
    which were skipped, LLM quota usage,
    and any errors per run.
    """

    __tablename__ = "fundamental_analysis_log"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    run_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    markets_processed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    markets_skipped: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    markets_vetoed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    llm_calls_made: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    llm_calls_failed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    # JSON: {model_id: call_count} for this run.
    model_usage_json: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    duration_seconds: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="completed"
    )
