"""Maintenance of the full-text search index (book_fts).

Kept in sync manually (call reindex_book after any change to a book's title,
author, description or subjects) rather than via SQL triggers, because the
indexed text spans three tables (books, authors, subjects).

Dialect-aware (Phase 4): SQLite uses a contentless FTS5 virtual table
(rowid-keyed); Postgres gets a plain table keyed by `id` and is searched
with ILIKE (full tsvector/trigram parity is a future enhancement).
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from libarr.models import Book


def reindex_book(session: Session, book_id: int) -> None:
    """Rebuild the search row for a book from its current title/author/description/subjects."""
    book = session.get(Book, book_id)
    if book is None:
        return
    title = book.title or ""
    author = book.author.name if book.author else ""
    description = book.description or ""
    subjects = ", ".join(sorted(s.name for s in book.subjects))

    key = "rowid" if session.get_bind().dialect.name == "sqlite" else "id"
    session.execute(text(f"DELETE FROM book_fts WHERE {key} = :id"), {"id": book_id})
    session.execute(
        text(
            f"INSERT INTO book_fts({key}, title, author, description, subjects) "
            "VALUES (:id, :title, :author, :description, :subjects)"
        ),
        {
            "id": book_id,
            "title": title,
            "author": author,
            "description": description,
            "subjects": subjects,
        },
    )
