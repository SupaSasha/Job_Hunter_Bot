"""Enable Himalayas while preserving existing source selections.

Revision ID: a814d5c0732e
Revises: f72c4ea83910
"""

import sqlalchemy as sa
from alembic import op

revision = "a814d5c0732e"
down_revision = "f72c4ea83910"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "user_filters",
        "sources",
        server_default=sa.text(
            "'{remoteok,getonboard,weworkremotely,himalayas}'::varchar[]"
        ),
    )
    op.execute(
        "UPDATE user_filters SET sources = array_append(sources, 'himalayas') "
        "WHERE NOT ('himalayas' = ANY(sources))"
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM user_filters "
            "WHERE array_remove(sources, 'himalayas') = '{}'::varchar[])"
        )
    ):
        raise RuntimeError(
            "Downgrade requires review of Himalayas-only source selections"
        )
    op.execute("UPDATE user_filters SET sources = array_remove(sources, 'himalayas')")
    op.alter_column(
        "user_filters",
        "sources",
        server_default=sa.text("'{remoteok,weworkremotely,getonboard}'::varchar[]"),
    )
