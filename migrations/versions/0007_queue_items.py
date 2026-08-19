"""queue_items table

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "queue_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("release_guid", sa.String(length=255), nullable=False, unique=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("indexer_name", sa.String(length=64), nullable=False),
        sa.Column("download_url", sa.String(length=1024), nullable=True),
        sa.Column("format", sa.String(length=16), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("queue_items")
