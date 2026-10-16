"""Enable Hacker News without resetting existing filter preferences.

Revision ID: d749a8b3e205
Revises: c638e7a2910f
"""

import sqlalchemy as sa
from alembic import op

revision = "d749a8b3e205"
down_revision = "c638e7a2910f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "user_filters",
        "sources",
        server_default=sa.text(
            "'{remoteok,getonboard,weworkremotely,himalayas,jobicy,the_muse,hacker_news}'::varchar[]"
        ),
    )
    op.execute(
        "UPDATE user_filters SET sources = array_append(sources, 'hacker_news') "
        "WHERE NOT ('hacker_news' = ANY(sources))"
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM user_filters "
            "WHERE array_remove(sources, 'hacker_news') = '{}'::varchar[])"
        )
    ):
        raise RuntimeError("Downgrade requires review of Hacker News-only selections")
    op.execute("UPDATE user_filters SET sources = array_remove(sources, 'hacker_news')")
    op.alter_column(
        "user_filters",
        "sources",
        server_default=sa.text(
            "'{remoteok,getonboard,weworkremotely,himalayas,jobicy,the_muse}'::varchar[]"
        ),
    )
