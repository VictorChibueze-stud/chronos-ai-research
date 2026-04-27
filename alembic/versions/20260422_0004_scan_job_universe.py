"""Add universe_name column to scan_job_log.

Revision ID: 20260422_0004
Revises: 20260422_0003
Create Date: 2026-04-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260422_0004"
down_revision = "20260422_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scan_job_log",
        sa.Column("universe_name", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scan_job_log", "universe_name")
