"""Maintenance of the contentless FTS5 search index (book_fts).

Kept in sync manually (call reindex_book after any change to a book's title,
author, description or subjects) rather than via SQL triggers, because the
indexed text spans three tables (books, authors, subjects).
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from libarr.models import Book


def reindex_book(session: Session, book_id: int) -> None:
    """Rebuild the FTS row for a book from its current title/author/description/subjects."""
    book = session.get(Book, book_id)
    if book is None:
        return
    title = book.title or ""
    author = book.author.name if book.author else ""
    description = book.description or ""
    subjects = ", ".join(sorted(s.name for s in book.subjects))

    session.execute(text("DELETE FROM book_fts WHERE rowid = :id"), {"id": book_id})
    session.execute(
        text(
            "INSERT INTO book_fts(rowid, title, author, description, subjects) "
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
