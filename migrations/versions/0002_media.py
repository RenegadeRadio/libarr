"""media tables: authors, series, books, editions, files, subjects, book_fts

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "authors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("sort_name", sa.String(length=255), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=True),
        sa.Column("biography", sa.Text(), nullable=True),
        sa.Column("ol_key", sa.String(length=64), nullable=True, unique=True),
        sa.Column("cover_path", sa.String(length=1024), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "series",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("authors.id"), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_table(
        "books",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("authors.id"), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("subtitle", sa.String(length=512), nullable=True),
        sa.Column("series_id", sa.Integer(), sa.ForeignKey("series.id"), nullable=True),
        sa.Column("series_position", sa.Integer(), nullable=True),
        sa.Column("work_key", sa.String(length=64), nullable=True, unique=True),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("cover_path", sa.String(length=1024), nullable=True),
        sa.Column("monitored", sa.Boolean(), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("date_added", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "editions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("isbn13", sa.String(length=13), nullable=True, unique=True),
        sa.Column("isbn10", sa.String(length=10), nullable=True),
        sa.Column("publisher", sa.String(length=255), nullable=True),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("format", sa.String(length=32), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("ol_edition_key", sa.String(length=64), nullable=True),
        sa.Column("google_volume_id", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
    )
    op.create_table(
        "files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("edition_id", sa.Integer(), sa.ForeignKey("editions.id"), nullable=True),
        sa.Column("path", sa.String(length=1024), nullable=False, unique=True),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("date_added", sa.DateTime(), nullable=False),
        sa.Column("date_scanned", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "subjects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.UniqueConstraint("book_id", "slug", name="uq_subject_book_slug"),
    )
    op.create_index("ix_files_format", "files", ["format"])
    op.execute(
        "CREATE VIRTUAL TABLE book_fts USING fts5("
        "title, author, description, subjects, content='')"
    )


def downgrade() -> None:
    op.execute("DROP TABLE book_fts")
    op.drop_index("ix_files_format", table_name="files")
    op.drop_table("subjects")
    op.drop_table("files")
    op.drop_table("editions")
    op.drop_table("books")
    op.drop_table("series")
    op.drop_table("authors")
