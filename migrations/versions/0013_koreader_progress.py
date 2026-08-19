"""koreader_progress table

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "koreader_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("document", sa.String(length=512), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("device", sa.String(length=64), nullable=True),
        sa.Column("client", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "document", name="uq_koreader_user_doc"),
    )


def downgrade() -> None:
    op.drop_table("koreader_progress")
