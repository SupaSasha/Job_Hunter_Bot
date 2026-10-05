"""Add interface language with English default for every existing user.

Revision ID: e93b6472a105
Revises: c41a9e327b60
"""

import sqlalchemy as sa
from alembic import op

revision = "e93b6472a105"
down_revision = "c41a9e327b60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("language", sa.String(2), nullable=False, server_default="en"),
    )
    op.create_check_constraint("ck_users_language", "users", "language IN ('en', 'es')")


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM users WHERE language <> 'en')")
    ):
        raise RuntimeError("Downgrade requires manual review of saved language choices")
    op.drop_constraint("ck_users_language", "users", type_="check")
    op.drop_column("users", "language")
