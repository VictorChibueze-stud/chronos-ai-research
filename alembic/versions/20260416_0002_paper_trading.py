"""Add paper_accounts and paper_trades tables.

Revision ID: 20260416_0002
Revises: 20260416_0001
Create Date: 2026-04-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text


revision = "20260416_0002"
down_revision = "20260416_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("account_type", sa.String(), nullable=False),
        sa.Column("balance_usd", sa.Float(), nullable=False),
        sa.Column("initial_balance_usd", sa.Float(), nullable=False),
        sa.Column("drawdown_limit_pct", sa.Float(), nullable=False),
        sa.Column("risk_per_trade_pct", sa.Float(), nullable=False),
        sa.Column("max_concurrent_positions", sa.Integer(), nullable=False),
        sa.Column("scale_by_score", sa.Boolean(), nullable=False),
        sa.Column("entry_ema_fast", sa.Integer(), nullable=False),
        sa.Column("entry_ema_slow", sa.Integer(), nullable=False),
        sa.Column("entry_timeframe", sa.String(), nullable=False),
        sa.Column("min_market_state", sa.String(), nullable=False),
        sa.Column("tp_mode", sa.String(), nullable=False),
        sa.Column("time_exit_days", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_paused_drawdown", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "paper_trades",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("stop_price", sa.Float(), nullable=False),
        sa.Column("take_profit_price", sa.Float(), nullable=True),
        sa.Column("lot_size", sa.Float(), nullable=False),
        sa.Column("risk_amount_usd", sa.Float(), nullable=False),
        sa.Column("market_state_at_entry", sa.String(), nullable=True),
        sa.Column("score_at_entry", sa.Float(), nullable=True),
        sa.Column("entry_timeframe", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("open_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_price", sa.Float(), nullable=True),
        sa.Column("pnl_usd", sa.Float(), nullable=True),
        sa.Column("pnl_pct", sa.Float(), nullable=True),
        sa.Column("max_adverse_excursion_usd", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["paper_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_paper_trades_account_id",
        "paper_trades",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        "ix_paper_trades_symbol",
        "paper_trades",
        ["symbol"],
        unique=False,
    )
    op.create_index(
        "ix_paper_trades_status",
        "paper_trades",
        ["status"],
        unique=False,
    )
    op.execute(
        text("CREATE INDEX ix_paper_trades_open_at_desc ON paper_trades (open_at DESC)")
    )


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS ix_paper_trades_open_at_desc"))
    op.drop_index("ix_paper_trades_status", table_name="paper_trades")
    op.drop_index("ix_paper_trades_symbol", table_name="paper_trades")
    op.drop_index("ix_paper_trades_account_id", table_name="paper_trades")
    op.drop_table("paper_trades")
    op.drop_table("paper_accounts")
