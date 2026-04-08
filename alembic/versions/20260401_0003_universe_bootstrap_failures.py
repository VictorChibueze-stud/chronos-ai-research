"""Add universe_bootstrap_failures for readiness ERROR state.

Revision ID: 20260401_0003
Revises: 20260401_0002
Create Date: 2026-04-01 12:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260401_0003"
down_revision = "20260401_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "universe_bootstrap_failures",
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("symbol"),
    )


def downgrade() -> None:
    op.drop_table("universe_bootstrap_failures")
