"""Add universe column to paper_accounts.

Revision ID: 20260421_0002
Revises: 20260421_0001
Create Date: 2026-04-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260421_0002"
down_revision = "20260421_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "paper_accounts",
        sa.Column("universe", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("paper_accounts", "universe")
