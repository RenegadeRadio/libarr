"""conversion_jobs table + users.notify_events

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversion_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("file_id", sa.Integer(), sa.ForeignKey("files.id"), nullable=False),
        sa.Column("target_format", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("output_path", sa.String(length=1024), nullable=True),
        sa.Column("error", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.add_column(
        "users",
        sa.Column(
            "notify_events",
            sa.String(length=512),
            nullable=False,
            server_default='["import","search"]',
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "notify_events")
    op.drop_table("conversion_jobs")
