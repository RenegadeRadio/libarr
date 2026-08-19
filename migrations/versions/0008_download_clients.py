"""download_clients table + queue_items tracking columns

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "download_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False, unique=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("url", sa.String(length=512), nullable=True),
        sa.Column("username", sa.String(length=128), nullable=True),
        sa.Column("password", sa.String(length=255), nullable=True),
        sa.Column("api_key", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("remote_path", sa.String(length=512), nullable=True),
        sa.Column("local_path", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.add_column("queue_items", sa.Column("client_name", sa.String(length=64), nullable=True))
    op.add_column(
        "queue_items", sa.Column("client_download_id", sa.String(length=255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("queue_items", "client_download_id")
    op.drop_column("queue_items", "client_name")
    op.drop_table("download_clients")
