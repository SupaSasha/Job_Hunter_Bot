"""Harden delivery retries and digest reservations

Revision ID: 49f75b591334
Revises: 9f28bc7d43a6
Create Date: 2026-10-02 12:41:52.101985

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "49f75b591334"
down_revision: Union[str, Sequence[str], None] = "9f28bc7d43a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Preserve all rows; legacy failed notifications remain non-retryable."""
    op.drop_constraint("ck_notifications_status", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notifications_status",
        "notifications",
        "status IN ('pending', 'sent', 'failed', 'retryable', 'unknown')",
    )
    op.drop_constraint("ck_digest_status", "digest_runs", type_="check")
    op.create_check_constraint(
        "ck_digest_status",
        "digest_runs",
        "status IN ('pending', 'empty', 'sent', 'partial', 'failed', 'abandoned')",
    )
    op.drop_constraint(op.f("uq_digest_user_date"), "digest_runs", type_="unique")
    op.create_index(
        "uq_digest_user_date",
        "digest_runs",
        ["user_id", "local_date"],
        unique=True,
        postgresql_where=sa.text("status <> 'abandoned'"),
    )
    op.create_index("ix_jobs_collected_at", "jobs", ["collected_at"], unique=False)
    op.create_index(
        "ix_jobs_fingerprint_collected_at",
        "jobs",
        ["fingerprint", "collected_at"],
        unique=False,
    )
    op.add_column(
        "notifications",
        sa.Column("retry_after_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Refuse loss of delivery certainty or abandoned history on downgrade."""
    incompatible = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM notifications "
            "WHERE status IN ('retryable', 'unknown')) "
            "OR EXISTS (SELECT 1 FROM digest_runs WHERE status = 'abandoned')"
        )
    )
    if incompatible:
        raise RuntimeError("Downgrade requires manual review of new delivery states")
    op.drop_constraint("ck_notifications_status", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notifications_status",
        "notifications",
        "status IN ('pending', 'sent', 'failed')",
    )
    op.drop_constraint("ck_digest_status", "digest_runs", type_="check")
    op.create_check_constraint(
        "ck_digest_status",
        "digest_runs",
        "status IN ('pending', 'empty', 'sent', 'partial', 'failed')",
    )
    op.drop_column("notifications", "retry_after_until")
    op.drop_index("ix_jobs_fingerprint_collected_at", table_name="jobs")
    op.drop_index("ix_jobs_collected_at", table_name="jobs")
    op.drop_index(
        "uq_digest_user_date",
        table_name="digest_runs",
        postgresql_where=sa.text("status <> 'abandoned'"),
    )
    op.create_unique_constraint(
        op.f("uq_digest_user_date"),
        "digest_runs",
        ["user_id", "local_date"],
        postgresql_nulls_not_distinct=False,
    )
