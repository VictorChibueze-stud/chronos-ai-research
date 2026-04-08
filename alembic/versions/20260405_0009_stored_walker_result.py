"""Add stored_walker_result.

Revision ID: 20260405_0009
Revises: 20260404_0008
Create Date: 2026-04-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260405_0009"
down_revision = "20260404_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stored_walker_result",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("source_timeframe", sa.String(), nullable=False),
        sa.Column("walker_state_json", sa.JSON(), nullable=False),
        sa.Column("max_depth_reached", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_mitigation_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("waiting_for", sa.String(), nullable=True),
        sa.Column("global_choch_zone_json", sa.JSON(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_stored_walker_result_symbol", "stored_walker_result", ["symbol"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_stored_walker_result_symbol", table_name="stored_walker_result")
    op.drop_table("stored_walker_result")
