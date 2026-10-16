"""Enable The Muse while preserving existing filter preferences.

Revision ID: c638e7a2910f
Revises: b927c64ed108
"""

import sqlalchemy as sa
from alembic import op

revision = "c638e7a2910f"
down_revision = "b927c64ed108"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "user_filters",
        "sources",
        server_default=sa.text(
            "'{remoteok,getonboard,weworkremotely,himalayas,jobicy,the_muse}'::varchar[]"
        ),
    )
    op.execute(
        "UPDATE user_filters SET sources = array_append(sources, 'the_muse') "
        "WHERE NOT ('the_muse' = ANY(sources))"
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM user_filters "
            "WHERE array_remove(sources, 'the_muse') = '{}'::varchar[])"
        )
    ):
        raise RuntimeError(
            "Downgrade requires review of The Muse-only source selections"
        )
    op.execute("UPDATE user_filters SET sources = array_remove(sources, 'the_muse')")
    op.alter_column(
        "user_filters",
        "sources",
        server_default=sa.text(
            "'{remoteok,getonboard,weworkremotely,himalayas,jobicy}'::varchar[]"
        ),
    )
