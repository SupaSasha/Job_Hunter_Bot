"""Allow manual digests without consuming the scheduled daily attempt.

Revision ID: f72c4ea83910
Revises: e93b6472a105
"""

import sqlalchemy as sa
from alembic import op

revision = "f72c4ea83910"
down_revision = "e93b6472a105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "digest_runs",
        sa.Column("manual", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.drop_index("uq_digest_user_date", table_name="digest_runs")
    op.create_index(
        "uq_digest_user_date",
        "digest_runs",
        ["user_id", "local_date"],
        unique=True,
        postgresql_where=sa.text("status <> 'abandoned' AND NOT manual"),
    )
    op.create_index(
        "uq_digest_manual_pending_user",
        "digest_runs",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("manual AND status = 'pending'"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM digest_runs WHERE manual)")
    ):
        raise RuntimeError("Downgrade requires manual review of manual digest history")
    op.drop_index("uq_digest_manual_pending_user", table_name="digest_runs")
    op.drop_index("uq_digest_user_date", table_name="digest_runs")
    op.create_index(
        "uq_digest_user_date",
        "digest_runs",
        ["user_id", "local_date"],
        unique=True,
        postgresql_where=sa.text("status <> 'abandoned'"),
    )
    op.drop_column("digest_runs", "manual")
