"""Scanner settings latest and audit history.

Revision ID: 20260401_0005
Revises: 20260401_0004
Create Date: 2026-04-01 21:10:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260401_0005"
down_revision = "20260401_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scan_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("settings_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scan_settings_scope", "scan_settings", ["scope"], unique=True)

    op.create_table(
        "scan_settings_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("settings_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scan_settings_history_scope", "scan_settings_history", ["scope"])
    op.create_index("ix_scan_settings_history_created_at", "scan_settings_history", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_scan_settings_history_created_at", table_name="scan_settings_history")
    op.drop_index("ix_scan_settings_history_scope", table_name="scan_settings_history")
    op.drop_table("scan_settings_history")
    op.drop_index("ix_scan_settings_scope", table_name="scan_settings")
    op.drop_table("scan_settings")
