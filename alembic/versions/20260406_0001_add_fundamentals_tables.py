"""Add fundamentals tables.

Revision ID: 20260406_0001
Revises: 20260405_0009
Create Date: 2026-04-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260406_0001"
down_revision = "20260405_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "economic_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("event_name", sa.String(length=255), nullable=False),
        sa.Column("event_category", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("impact_level", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("forecast_value", sa.String(length=50), nullable=True),
        sa.Column("actual_value", sa.String(length=50), nullable=True),
        sa.Column("previous_value", sa.String(length=50), nullable=True),
        sa.Column("affected_markets", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_name", "scheduled_at", name="uq_economic_event"),
    )
    op.create_index("ix_economic_events_scheduled_at", "economic_events", ["scheduled_at"], unique=False)

    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("headline", sa.String(length=500), nullable=False),
        sa.Column("source_name", sa.String(length=100), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("market_tags", sa.JSON(), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("economic_events.id"), nullable=True),
        sa.Column("fetch_snapshot", sa.String(length=10), nullable=True),
        sa.Column("sentiment_label", sa.String(length=20), nullable=False),
        sa.Column("sentiment_score", sa.Float(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_news_articles_published_at", "news_articles", ["published_at"], unique=False)
    op.create_index("ix_news_articles_url", "news_articles", ["url"], unique=True)

    op.create_table(
        "fundamental_event_impact",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("market_symbol", sa.String(length=50), nullable=False),
        sa.Column("event_category", sa.String(length=100), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("median_shock_pct", sa.Float(), nullable=False),
        sa.Column("median_recovery_hours", sa.Float(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("market_symbol", "event_category", name="uq_event_impact"),
    )
    op.create_index(
        "ix_fundamental_event_impact_market_symbol",
        "fundamental_event_impact",
        ["market_symbol"],
        unique=False,
    )

    op.create_table(
        "event_impact_ranking",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("market_symbol", sa.String(length=50), nullable=False),
        sa.Column("event_category", sa.String(length=100), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("median_shock_pct", sa.Float(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("market_symbol", "event_category", name="uq_impact_ranking"),
    )
    op.create_index(
        "ix_event_impact_ranking_market_symbol",
        "event_impact_ranking",
        ["market_symbol"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_event_impact_ranking_market_symbol", table_name="event_impact_ranking")
    op.drop_table("event_impact_ranking")

    op.drop_index("ix_fundamental_event_impact_market_symbol", table_name="fundamental_event_impact")
    op.drop_table("fundamental_event_impact")

    op.drop_index("ix_news_articles_url", table_name="news_articles")
    op.drop_index("ix_news_articles_published_at", table_name="news_articles")
    op.drop_table("news_articles")

    op.drop_index("ix_economic_events_scheduled_at", table_name="economic_events")
    op.drop_table("economic_events")
