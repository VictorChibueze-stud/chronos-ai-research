"""Add global_structure_cache.

Revision ID: 20260404_0007
Revises: 20260401_0006
Create Date: 2026-04-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260404_0007"
down_revision = "20260401_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "global_structure_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("reference_timeframe", sa.String(), nullable=False),
        sa.Column("confirmed_leg_count", sa.Integer(), nullable=False),
        sa.Column("legs_json", sa.JSON(), nullable=False),
        sa.Column("bos_levels_json", sa.JSON(), nullable=False),
        sa.Column("choch_zone_json", sa.JSON(), nullable=True),
        sa.Column("choch_level_json", sa.JSON(), nullable=True),
        sa.Column("trend_direction", sa.String(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candle_start_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candle_end_timestamp", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_global_structure_cache_symbol",
        "global_structure_cache",
        ["symbol"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_global_structure_cache_symbol", "global_structure_cache", type_="unique")
    op.drop_table("global_structure_cache")
