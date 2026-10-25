"""Default future filter rows to Worldwide; never rewrite existing preferences.

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "a2b3c4d5e6f7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "user_filters",
        "allowed_regions",
        server_default=sa.text("'{worldwide}'::varchar[]"),
    )


def downgrade() -> None:
    op.alter_column(
        "user_filters", "allowed_regions", server_default=sa.text("'{}'::varchar[]")
    )
