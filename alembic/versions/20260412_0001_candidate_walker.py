"""Add candidate_walker_json column to candidate_impulse_cache.

Revision ID: 20260412_0001
Revises: 20260410_0012
Create Date: 2026-04-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260412_0001"
down_revision = "20260410_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate_impulse_cache",
        sa.Column("candidate_walker_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidate_impulse_cache", "candidate_walker_json")
