"""shelves + shelf_books tables

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shelves",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "shelf_books",
        sa.Column("shelf_id", sa.Integer(), sa.ForeignKey("shelves.id"), primary_key=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id"), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("shelf_books")
    op.drop_table("shelves")
