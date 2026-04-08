"""Add active universe symbols and signal history.

Revision ID: 20260401_0002
Revises: 20260401_0001
Create Date: 2026-04-01 00:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260401_0002"
down_revision = "20260401_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "active_universe_symbols",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_active_universe_symbols_symbol",
        "active_universe_symbols",
        ["symbol"],
        unique=True,
    )

    op.create_table(
        "signal_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("signal", sa.String(), nullable=False),
        sa.Column("trend_direction", sa.String(), nullable=True),
        sa.Column("trend_score", sa.Float(), nullable=True),
        sa.Column("emitted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_signal_history_symbol", "signal_history", ["symbol"], unique=False)
    op.create_index("ix_signal_history_timeframe", "signal_history", ["timeframe"], unique=False)
    op.create_index("ix_signal_history_emitted_at", "signal_history", ["emitted_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_signal_history_emitted_at", table_name="signal_history")
    op.drop_index("ix_signal_history_timeframe", table_name="signal_history")
    op.drop_index("ix_signal_history_symbol", table_name="signal_history")
    op.drop_table("signal_history")

    op.drop_index("ix_active_universe_symbols_symbol", table_name="active_universe_symbols")
    op.drop_table("active_universe_symbols")
