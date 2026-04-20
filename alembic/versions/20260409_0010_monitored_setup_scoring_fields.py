"""Add scoring fields to monitored_setups.

Revision ID: 20260409_0010
Revises: 20260406_0001
Create Date: 2026-04-09
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260409_0010"
down_revision = "20260406_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "monitored_setups",
        sa.Column("candidate_ichoch_reached", sa.Boolean(), nullable=True, server_default=None)
    )
    op.add_column(
        "monitored_setups",
        sa.Column("new_move_active", sa.Boolean(), nullable=True, server_default=None)
    )
    op.add_column(
        "monitored_setups",
        sa.Column("normalised_distance_to_bos", sa.Float(), nullable=True, server_default=None)
    )


def downgrade() -> None:
    op.drop_column("monitored_setups", "normalised_distance_to_bos")
    op.drop_column("monitored_setups", "new_move_active")
    op.drop_column("monitored_setups", "candidate_ichoch_reached")
