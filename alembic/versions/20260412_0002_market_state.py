"""Add market_state columns and market_state_history table.

Revision ID: 20260412_0002
Revises: 20260412_0001
Create Date: 2026-04-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260412_0002"
down_revision = "20260412_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "global_structure_cache",
        sa.Column("market_state", sa.String(), nullable=True),
    )
    op.add_column(
        "monitored_setups",
        sa.Column("market_state", sa.String(), nullable=True),
    )
    op.create_table(
        "market_state_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("previous_state", sa.String(), nullable=True),
        sa.Column(
            "transitioned_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("trend_score", sa.Float(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_market_state_history_symbol",
        "market_state_history",
        ["symbol"],
    )
    op.create_index(
        "ix_market_state_history_symbol_transitioned_at",
        "market_state_history",
        ["symbol", "transitioned_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_market_state_history_symbol_transitioned_at",
        table_name="market_state_history",
    )
    op.drop_index(
        "ix_market_state_history_symbol",
        table_name="market_state_history",
    )
    op.drop_table("market_state_history")
    op.drop_column("monitored_setups", "market_state")
    op.drop_column("global_structure_cache", "market_state")
