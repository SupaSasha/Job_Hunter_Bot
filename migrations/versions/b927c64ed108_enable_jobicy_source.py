"""Enable Jobicy while preserving existing filter preferences.

Revision ID: b927c64ed108
Revises: a814d5c0732e
"""

import sqlalchemy as sa
from alembic import op

revision = "b927c64ed108"
down_revision = "a814d5c0732e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "user_filters",
        "sources",
        server_default=sa.text(
            "'{remoteok,getonboard,weworkremotely,himalayas,jobicy}'::varchar[]"
        ),
    )
    op.execute(
        "UPDATE user_filters SET sources = array_append(sources, 'jobicy') "
        "WHERE NOT ('jobicy' = ANY(sources))"
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM user_filters "
            "WHERE array_remove(sources, 'jobicy') = '{}'::varchar[])"
        )
    ):
        raise RuntimeError("Downgrade requires review of Jobicy-only source selections")
    op.execute("UPDATE user_filters SET sources = array_remove(sources, 'jobicy')")
    op.alter_column(
        "user_filters",
        "sources",
        server_default=sa.text(
            "'{remoteok,getonboard,weworkremotely,himalayas}'::varchar[]"
        ),
    )
