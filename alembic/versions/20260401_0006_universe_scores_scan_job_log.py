"""Add universe_scores and scan_job_log.

Revision ID: 20260401_0006
Revises: 20260401_0005
Create Date: 2026-04-01 22:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260401_0006"
down_revision = "20260401_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "universe_scores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("timeframe_basis", sa.String(length=16), nullable=False),
        sa.Column("trend_direction", sa.String(length=16), nullable=False),
        sa.Column("confirmed_leg_count", sa.Integer(), nullable=False),
        sa.Column("leg_structure_json", sa.JSON(), nullable=False),
        sa.Column("impulse_price_ratio", sa.Float(), nullable=False),
        sa.Column("impulse_velocity_ratio", sa.Float(), nullable=False),
        sa.Column("retracement_phase_bonus", sa.Float(), nullable=False),
        sa.Column("candidate_impulse_bonus", sa.Float(), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("universe_rank", sa.Integer(), nullable=True),
        sa.Column("last_computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computation_duration_seconds", sa.Float(), nullable=True),
    )
    op.create_index("ix_universe_scores_symbol", "universe_scores", ["symbol"], unique=True)

    op.create_table(
        "scan_job_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("total_symbols", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.String(length=2048), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("scan_job_log")
    op.drop_index("ix_universe_scores_symbol", table_name="universe_scores")
    op.drop_table("universe_scores")
