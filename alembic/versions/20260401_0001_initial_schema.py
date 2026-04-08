"""Initial PostgreSQL schema.

Revision ID: 20260401_0001
Revises:
Create Date: 2026-04-01 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260401_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("killswitch_active", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "monitored_setups",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("htf_timeframe", sa.String(), nullable=False),
        sa.Column("htf_trend_direction", sa.String(), nullable=False),
        sa.Column("current_phase", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'SCANNING'")),
        sa.Column("ema_signal", sa.String(), nullable=True),
        sa.Column("trend_score", sa.Float(), nullable=False),
        sa.Column("structural_state_json", sa.JSON(), nullable=False),
        sa.Column("mtf_alignment", sa.JSON(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_monitored_setups_symbol", "monitored_setups", ["symbol"], unique=False)

    op.create_table(
        "alert_zones",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("setup_id", sa.Integer(), sa.ForeignKey("monitored_setups.id"), nullable=False),
        sa.Column("zone_type", sa.String(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=True),
        sa.Column("price_high", sa.Float(), nullable=False),
        sa.Column("price_low", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("watch_condition", sa.String(), nullable=False),
        sa.Column("is_manual_override", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "candle_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_candle_cache"),
    )
    op.create_index("ix_candle_cache_symbol", "candle_cache", ["symbol"], unique=False)
    op.create_index("ix_candle_cache_timeframe", "candle_cache", ["timeframe"], unique=False)
    op.create_index("ix_candle_cache_timestamp", "candle_cache", ["timestamp"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_candle_cache_timestamp", table_name="candle_cache")
    op.drop_index("ix_candle_cache_timeframe", table_name="candle_cache")
    op.drop_index("ix_candle_cache_symbol", table_name="candle_cache")
    op.drop_table("candle_cache")
    op.drop_table("alert_zones")
    op.drop_index("ix_monitored_setups_symbol", table_name="monitored_setups")
    op.drop_table("monitored_setups")
    op.drop_table("system_settings")
