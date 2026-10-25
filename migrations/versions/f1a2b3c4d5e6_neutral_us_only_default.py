"""Use a neutral US eligibility default for future rows; preserve saved filters.

Revision ID: f1a2b3c4d5e6
Revises: d0e7c42b6a91
"""

import sqlalchemy as sa
from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "d0e7c42b6a91"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("user_filters", "exclude_us_only", server_default=sa.text("false"))


def downgrade() -> None:
    op.alter_column("user_filters", "exclude_us_only", server_default=sa.text("true"))
