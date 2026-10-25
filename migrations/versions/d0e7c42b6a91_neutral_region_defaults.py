"""Make new user region preferences neutral without rewriting saved filters.

Revision ID: d0e7c42b6a91
Revises: e85ab9c12460
"""

import sqlalchemy as sa
from alembic import op

revision = "d0e7c42b6a91"
down_revision = "e85ab9c12460"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "user_filters",
        "allowed_regions",
        server_default=sa.text("'{}'::varchar[]"),
    )


def downgrade() -> None:
    op.alter_column(
        "user_filters",
        "allowed_regions",
        server_default=sa.text("'{worldwide,latam,south_america,uruguay}'::varchar[]"),
    )
