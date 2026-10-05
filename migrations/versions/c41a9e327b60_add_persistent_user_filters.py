"""Add persistent per-user job filters without changing existing tables.

Revision ID: c41a9e327b60
Revises: 49f75b591334
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c41a9e327b60"
down_revision = "49f75b591334"
branch_labels = None
depends_on = None


def upgrade() -> None:
    empty_lists = (
        "keywords",
        "required_technologies",
        "preferred_technologies",
        "excluded_technologies",
        "employment_types",
        "experience_levels",
        "blacklisted_words",
        "blacklisted_companies",
    )
    op.create_table(
        "user_filters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        *[
            sa.Column(
                field,
                postgresql.ARRAY(sa.String()),
                nullable=False,
                server_default=sa.text("'{}'::varchar[]"),
            )
            for field in empty_lists
        ],
        sa.Column("min_salary", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column(
            "allowed_regions",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text(
                "'{worldwide,latam,south_america,uruguay}'::varchar[]"
            ),
        ),
        sa.Column(
            "remote_only", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "exclude_us_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "sources",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{remoteok,weworkremotely,getonboard}'::varchar[]"),
        ),
        sa.Column(
            "timezone_tolerance_hours", sa.Integer(), nullable=False, server_default="2"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", name="uq_user_filters_user_id"),
        sa.CheckConstraint("min_salary >= 0", name="ck_user_filters_min_salary"),
        sa.CheckConstraint(
            "timezone_tolerance_hours BETWEEN 0 AND 4",
            name="ck_user_filters_timezone_tolerance",
        ),
        sa.CheckConstraint("cardinality(sources) > 0", name="ck_user_filters_sources"),
    )


def downgrade() -> None:
    # Never silently erase user preferences during a rollback.
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM user_filters)")):
        raise RuntimeError("Downgrade requires manual review of saved user filters")
    op.drop_table("user_filters")
