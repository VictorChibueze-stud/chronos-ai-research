from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
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
