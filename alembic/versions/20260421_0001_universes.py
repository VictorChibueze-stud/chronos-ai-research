"""Add universe_settings and monitored_setups.universe.

Revision ID: 20260421_0001
Revises: 20260420_0001
Create Date: 2026-04-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260421_0001"
down_revision = "20260420_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "universe_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("universe_name", sa.String(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("rank_frequency", sa.String(), nullable=False),
        sa.Column("refresh_offset_hours", sa.Integer(), nullable=False),
        sa.Column("refresh_interval_hours", sa.Integer(), nullable=False),
        sa.Column("top_n", sa.Integer(), nullable=False),
        sa.Column("non_top_n_depth", sa.String(), nullable=False),
        sa.Column("category_min_slots_json", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("universe_name", name="uq_universe_settings_name"),
    )
    op.create_index(
        op.f("ix_universe_settings_universe_name"),
        "universe_settings",
        ["universe_name"],
        unique=False,
    )
    op.add_column(
        "monitored_setups",
        sa.Column("universe", sa.String(), nullable=True),
    )
    op.create_index(
        op.f("ix_monitored_setups_universe"),
        "monitored_setups",
        ["universe"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_monitored_setups_universe"), table_name="monitored_setups")
    op.drop_column("monitored_setups", "universe")
    op.drop_table("universe_settings")
