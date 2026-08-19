"""history_events + discovery_lists tables, authors.monitored

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "authors", sa.Column("monitored", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.create_table(
        "history_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id"), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("details", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "discovery_lists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("query", sa.String(length=1024), nullable=False),
        sa.Column("schedule_days", sa.Integer(), nullable=False),
        sa.Column("max_per_run", sa.Integer(), nullable=False),
        sa.Column("auto_monitor", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("discovery_lists")
    op.drop_table("history_events")
    op.drop_column("authors", "monitored")
