"""Add manual_structure_overrides table.

Revision ID: 20260420_0001
Revises: 20260416_0002
Create Date: 2026-04-20
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260420_0001"
down_revision = "20260416_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manual_structure_overrides",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("override_type", sa.String(), nullable=False),
        sa.Column("lower_boundary", sa.Float(), nullable=True),
        sa.Column("upper_boundary", sa.Float(), nullable=True),
        sa.Column("start_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trend_start_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trend_end_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("depth_index", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "override_type", name="uq_manual_override_symbol_type"),
    )
    op.create_index(
        op.f("ix_manual_structure_overrides_symbol"),
        "manual_structure_overrides",
        ["symbol"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_manual_structure_overrides_symbol"), table_name="manual_structure_overrides")
    op.drop_table("manual_structure_overrides")
