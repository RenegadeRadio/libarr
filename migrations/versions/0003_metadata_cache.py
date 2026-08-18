"""metadata_cache table

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "metadata_cache",
        sa.Column("provider", sa.String(length=32), primary_key=True),
        sa.Column("kind", sa.String(length=32), primary_key=True),
        sa.Column("key", sa.String(length=255), primary_key=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("etag", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("metadata_cache")
