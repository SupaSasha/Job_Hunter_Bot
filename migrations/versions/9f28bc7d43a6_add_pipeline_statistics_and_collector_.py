"""Add pipeline statistics and collector runs

Revision ID: 9f28bc7d43a6
Revises: 54383f510932
Create Date: 2026-09-30 11:15:40.651622

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f28bc7d43a6"
down_revision: Union[str, Sequence[str], None] = "54383f510932"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add telemetry while preserving existing daily digest reservations.

    Historical digest rows remain metrics_recorded=false; do not backfill
    selection counters from current jobs or treat them as measured zeroes.
    """
    op.create_table(
        "collector_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "received_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "new_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "duplicate_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "cross_source_duplicate_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "failed_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'failed', 'skipped')",
            name="ck_collector_run_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_collector_runs_source"), "collector_runs", ["source"], unique=False
    )
    op.create_index(
        op.f("ix_collector_runs_started_at"),
        "collector_runs",
        ["started_at"],
        unique=False,
    )
    op.add_column(
        "digest_runs",
        sa.Column(
            "metrics_recorded",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "digest_runs",
        sa.Column(
            "candidate_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.add_column(
        "digest_runs",
        sa.Column(
            "filter_rejected_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "digest_runs",
        sa.Column(
            "accepted_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.add_column(
        "digest_runs",
        sa.Column(
            "score_0_49_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "digest_runs",
        sa.Column(
            "score_50_59_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "digest_runs",
        sa.Column(
            "score_60_69_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "digest_runs",
        sa.Column(
            "score_70_79_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "digest_runs",
        sa.Column(
            "score_80_89_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "digest_runs",
        sa.Column(
            "score_90_100_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "digest_runs",
        sa.Column(
            "below_threshold_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("digest_runs", "below_threshold_count")
    op.drop_column("digest_runs", "score_90_100_count")
    op.drop_column("digest_runs", "score_80_89_count")
    op.drop_column("digest_runs", "score_70_79_count")
    op.drop_column("digest_runs", "score_60_69_count")
    op.drop_column("digest_runs", "score_50_59_count")
    op.drop_column("digest_runs", "score_0_49_count")
    op.drop_column("digest_runs", "accepted_count")
    op.drop_column("digest_runs", "filter_rejected_count")
    op.drop_column("digest_runs", "candidate_count")
    op.drop_column("digest_runs", "metrics_recorded")
    op.drop_index(op.f("ix_collector_runs_started_at"), table_name="collector_runs")
    op.drop_index(op.f("ix_collector_runs_source"), table_name="collector_runs")
    op.drop_table("collector_runs")
