"""Add candidate_impulse_cache table.

Revision ID: 20260410_0012
Revises: 20260409_0011
Create Date: 2026-04-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260410_0012"
down_revision = "20260409_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_impulse_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("source_timeframe", sa.String(length=10), nullable=False),
        sa.Column("start_price", sa.Float(), nullable=False),
        sa.Column("start_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("choch_source", sa.String(length=20), nullable=False),
        sa.Column("legs_json", sa.JSON(), nullable=False),
        sa.Column("bos_levels_json", sa.JSON(), nullable=True),
        sa.Column("choch_zone_json", sa.JSON(), nullable=True),
        sa.Column("prime_impulse_json", sa.JSON(), nullable=True),
        sa.Column("prime_choch_zone_json", sa.JSON(), nullable=True),
        sa.Column("structure_broken", sa.Boolean(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_candidate_impulse_cache_symbol",
        "candidate_impulse_cache",
        ["symbol"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_impulse_cache_symbol", table_name="candidate_impulse_cache")
    op.drop_table("candidate_impulse_cache")
