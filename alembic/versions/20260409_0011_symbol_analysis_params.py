"""Add symbol_analysis_params table.

Revision ID: 20260409_0011
Revises: 20260409_0010
Create Date: 2026-04-09
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260409_0011"
down_revision = "20260409_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "symbol_analysis_params",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_symbol_analysis_params_symbol",
        "symbol_analysis_params",
        ["symbol"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_symbol_analysis_params_symbol", table_name="symbol_analysis_params")
    op.drop_table("symbol_analysis_params")
