"""Add prime_impulse_structure.

Revision ID: 20260404_0008
Revises: 20260404_0007
Create Date: 2026-04-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260404_0008"
down_revision = "20260404_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prime_impulse_structure",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("source_timeframe", sa.String(), nullable=False),
        sa.Column("confirmed_leg_count", sa.Integer(), nullable=False),
        sa.Column("legs_json", sa.JSON(), nullable=False),
        sa.Column("bos_levels_json", sa.JSON(), nullable=False),
        sa.Column("choch_zone_json", sa.JSON(), nullable=True),
        sa.Column("impulse_start_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("impulse_end_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("impulse_start_price", sa.Float(), nullable=False),
        sa.Column("impulse_end_price", sa.Float(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_unique_constraint(
        "uq_prime_impulse_structure_symbol",
        "prime_impulse_structure",
        ["symbol"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_prime_impulse_structure_symbol", "prime_impulse_structure", type_="unique")
    op.drop_table("prime_impulse_structure")
