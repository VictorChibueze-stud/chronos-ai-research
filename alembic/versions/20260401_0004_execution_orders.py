"""Execution orders and events for paper trading audit trail.

Revision ID: 20260401_0004
Revises: 20260401_0003
Create Date: 2026-04-01 18:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260401_0004"
down_revision = "20260401_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_order_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("intent_json", sa.JSON(), nullable=False),
        sa.Column("provider_order_id", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_execution_orders_client_order_id", "execution_orders", ["client_order_id"], unique=True)
    op.create_index("ix_execution_orders_provider", "execution_orders", ["provider"])
    op.create_index("ix_execution_orders_symbol", "execution_orders", ["symbol"])
    op.create_index("ix_execution_orders_status", "execution_orders", ["status"])
    op.create_index("ix_execution_orders_provider_order_id", "execution_orders", ["provider_order_id"])

    op.create_table(
        "execution_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("execution_orders.id"), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("message", sa.String(length=1024), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_execution_events_order_id", "execution_events", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_execution_events_order_id", table_name="execution_events")
    op.drop_table("execution_events")
    op.drop_index("ix_execution_orders_provider_order_id", table_name="execution_orders")
    op.drop_index("ix_execution_orders_status", table_name="execution_orders")
    op.drop_index("ix_execution_orders_symbol", table_name="execution_orders")
    op.drop_index("ix_execution_orders_provider", table_name="execution_orders")
    op.drop_index("ix_execution_orders_client_order_id", table_name="execution_orders")
    op.drop_table("execution_orders")
