"""reading_progress table

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reading_progress",
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id"), primary_key=True),
        sa.Column("profile", sa.String(length=64), primary_key=True),
        sa.Column("position", sa.Float(), nullable=False),
        sa.Column("location", sa.String(length=512), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("reading_progress")
