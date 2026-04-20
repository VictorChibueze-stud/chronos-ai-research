"""Add contract_specs table.

Revision ID: 20260416_0001
Revises: 20260412_0002
Create Date: 2026-04-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260416_0001"
down_revision = "20260412_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contract_specs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("asset_class", sa.String(), nullable=False),
        sa.Column("pip_size", sa.Float(), nullable=False),
        sa.Column("point_value", sa.Float(), nullable=False),
        sa.Column("contract_size", sa.Float(), nullable=False),
        sa.Column("lot_size_min", sa.Float(), nullable=False),
        sa.Column("lot_size_max", sa.Float(), nullable=False),
        sa.Column("lot_size_step", sa.Float(), nullable=False),
        sa.Column("quote_currency", sa.String(), nullable=True),
        sa.Column("base_currency", sa.String(), nullable=True),
        sa.Column("is_crypto", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", name="uq_contract_specs_symbol"),
    )
    op.create_index(
        "ix_contract_specs_symbol",
        "contract_specs",
        ["symbol"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_contract_specs_symbol", table_name="contract_specs")
    op.drop_table("contract_specs")
