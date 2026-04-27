"""Add fundamentals intelligence tables and monitored_setups veto fields.

Creates two new tables that back the LLM-driven fundamentals
intelligence layer:

- ``fundamental_stories``: one row per symbol with the full structured
  LLM payload (stories, actors, timeline, upcoming events, risk
  summary) and a critical-veto flag.
- ``fundamental_analysis_log``: per-run audit of which markets were
  processed, skipped, vetoed, LLM quota usage, duration, and status.

Also augments ``monitored_setups`` with:

- ``critical_veto_flag`` (BOOLEAN, NOT NULL, default FALSE)
- ``fundamental_analyzed_at`` (TIMESTAMP WITH TIME ZONE, nullable)

Revision ID: 20260422_0005
Revises: 20260422_0004
Create Date: 2026-04-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260422_0005"
down_revision = "20260422_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fundamental_stories",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column(
            "prime_impulse_start",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("stories_json", sa.JSON(), nullable=False),
        sa.Column(
            "critical_veto_flag",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("veto_reason", sa.Text(), nullable=True),
        sa.Column(
            "veto_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("model_used", sa.String(length=100), nullable=True),
        sa.Column(
            "news_window_start",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "news_window_end",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "analyzed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "symbol", name="uq_fundamental_stories_symbol"
        ),
    )
    op.create_index(
        "ix_fundamental_stories_symbol",
        "fundamental_stories",
        ["symbol"],
    )

    op.create_table(
        "fundamental_analysis_log",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "run_date",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "markets_processed",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "markets_skipped",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "markets_vetoed",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "llm_calls_made",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "llm_calls_failed",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("model_usage_json", sa.JSON(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="completed",
        ),
    )
    op.create_index(
        "ix_fundamental_analysis_log_run_date",
        "fundamental_analysis_log",
        ["run_date"],
    )

    op.add_column(
        "monitored_setups",
        sa.Column(
            "critical_veto_flag",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "monitored_setups",
        sa.Column(
            "fundamental_analyzed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("monitored_setups", "fundamental_analyzed_at")
    op.drop_column("monitored_setups", "critical_veto_flag")

    op.drop_index(
        "ix_fundamental_analysis_log_run_date",
        table_name="fundamental_analysis_log",
    )
    op.drop_table("fundamental_analysis_log")

    op.drop_index(
        "ix_fundamental_stories_symbol",
        table_name="fundamental_stories",
    )
    op.drop_table("fundamental_stories")
