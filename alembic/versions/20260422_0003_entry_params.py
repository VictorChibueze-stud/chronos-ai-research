"""Add entry_lookback_candles and entry_check_interval_hours to paper_accounts.

Revision ID: 20260422_0003
Revises: 20260422_0002
Create Date: 2026-04-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260422_0003"
down_revision = "20260422_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "paper_accounts",
        sa.Column(
            "entry_lookback_candles",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3"),
        ),
    )
    op.add_column(
        "paper_accounts",
        sa.Column(
            "entry_check_interval_hours",
            sa.Float(),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("paper_accounts", "entry_check_interval_hours")
    op.drop_column("paper_accounts", "entry_lookback_candles")
