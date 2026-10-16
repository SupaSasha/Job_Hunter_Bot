"""Enable Jooble while preserving existing source selections and preferences.

Revision ID: e85ab9c12460
Revises: d749a8b3e205
"""

import sqlalchemy as sa
from alembic import op

revision = "e85ab9c12460"
down_revision = "d749a8b3e205"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "user_filters",
        "sources",
        server_default=sa.text(
            "'{remoteok,getonboard,weworkremotely,himalayas,jobicy,the_muse,hacker_news,jooble}'::varchar[]"
        ),
    )
    op.execute(
        "UPDATE user_filters SET sources = array_append(sources, 'jooble') "
        "WHERE NOT ('jooble' = ANY(sources))"
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM user_filters "
            "WHERE array_remove(sources, 'jooble') = '{}'::varchar[])"
        )
    ):
        raise RuntimeError("Downgrade requires review of Jooble-only source selections")
    op.execute("UPDATE user_filters SET sources = array_remove(sources, 'jooble')")
    op.alter_column(
        "user_filters",
        "sources",
        server_default=sa.text(
            "'{remoteok,getonboard,weworkremotely,himalayas,jobicy,the_muse,hacker_news}'::varchar[]"
        ),
    )
