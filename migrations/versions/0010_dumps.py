"""dump_rows + dump_isbns tables

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dump_rows",
        sa.Column("ol_key", sa.String(length=128), primary_key=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "dump_isbns",
        sa.Column("isbn13", sa.String(length=32), primary_key=True),
        sa.Column("edition_key", sa.String(length=128), nullable=False),
        sa.Column("work_key", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("dump_isbns")
    op.drop_table("dump_rows")
