"""Create analysis_result_cache table.

Revision ID: 20260422_0002
Revises: 20260422_0001
Create Date: 2026-04-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260422_0002"
down_revision = "20260422_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_result_cache",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column(
            "result_json",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column("params_hash", sa.String(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "ttl_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("14400"),
        ),
        sa.UniqueConstraint(
            "symbol",
            "timeframe",
            name="uq_analysis_cache_sym_tf",
        ),
    )
    op.create_index(
        "ix_analysis_result_cache_symbol",
        "analysis_result_cache",
        ["symbol"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_analysis_result_cache_symbol",
        table_name="analysis_result_cache",
    )
    op.drop_table("analysis_result_cache")
