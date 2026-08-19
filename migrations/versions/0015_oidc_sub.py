"""users.oidc_sub column

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("oidc_sub", sa.String(length=128), nullable=True))
        batch_op.create_unique_constraint("uq_users_oidc_sub", ["oidc_sub"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("uq_users_oidc_sub", type_="unique")
        batch_op.drop_column("oidc_sub")
