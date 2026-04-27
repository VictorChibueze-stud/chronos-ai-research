"""Sprint 1 manual override schema updates.

Adds raw user-input and expiry columns to manual_structure_overrides and
updates uniqueness to include depth_index with NULLS NOT DISTINCT semantics.

Revision ID: 20260426_0001
Revises: 20260422_0005
Create Date: 2026-04-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260426_0001"
down_revision = "20260422_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "manual_structure_overrides",
        sa.Column("approx_price_a", sa.Float(), nullable=True),
    )
    op.add_column(
        "manual_structure_overrides",
        sa.Column("approx_timestamp_a", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "manual_structure_overrides",
        sa.Column("approx_price_b", sa.Float(), nullable=True),
    )
    op.add_column(
        "manual_structure_overrides",
        sa.Column("approx_timestamp_b", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "manual_structure_overrides",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.drop_constraint(
        "uq_manual_override_symbol_type",
        "manual_structure_overrides",
        type_="unique",
    )

    op.execute(
        """
        ALTER TABLE manual_structure_overrides
        ADD CONSTRAINT uq_manual_override_symbol_type_depth
        UNIQUE NULLS NOT DISTINCT (symbol, override_type, depth_index)
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_manual_override_symbol_type_depth",
        "manual_structure_overrides",
        type_="unique",
    )

    op.create_unique_constraint(
        "uq_manual_override_symbol_type",
        "manual_structure_overrides",
        ["symbol", "override_type"],
    )

    op.drop_column("manual_structure_overrides", "expires_at")
    op.drop_column("manual_structure_overrides", "approx_timestamp_b")
    op.drop_column("manual_structure_overrides", "approx_price_b")
    op.drop_column("manual_structure_overrides", "approx_timestamp_a")
    op.drop_column("manual_structure_overrides", "approx_price_a")
