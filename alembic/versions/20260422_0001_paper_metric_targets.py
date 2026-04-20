"""Add metric_targets_json column to paper_accounts.

Revision ID: 20260422_0001
Revises: 20260421_0002
Create Date: 2026-04-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260422_0001"
down_revision = "20260421_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "paper_accounts",
        sa.Column("metric_targets_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("paper_accounts", "metric_targets_json")
