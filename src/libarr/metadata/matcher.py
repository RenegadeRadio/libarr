"""Match a candidate (title/author/ISBN) to a library book.

The import pipeline's second line of defense (plan §2.2 / Task 1.5):
1. ISBN-exact (normalized to ISBN-13) — the canonical join key.
2. Exact normalized title (+ author).
3. Title with edition keywords stripped ("The Stand Unabridged" → "The Stand").
4. FTS fallback for noisy titles — only when ≥2 non-stopword tokens overlap
   and the author agrees (when an author was given).
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from libarr.acquisition.parser import EDITION_KEYWORDS
from libarr.metadata.normalize import normalize_isbn, normalize_text
from libarr.models import Author, Book, Edition

STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "of",
    "or",
    "in",
    "on",
    "to",
    "for",
    "with",
    "by",
    "at",
    "de",
    "la",
    "le",
    "el",
    "il",
    "der",
    "die",
    "das",
}


def match_book(
    session: Session,
    *,
    title: str,
    author: str | None = None,
    isbn: str | None = None,
) -> Book | None:
    """Return the best library match for the candidate, or None."""
    if isbn:
        isbn13 = normalize_isbn(isbn)
        if isbn13 is not None:
            edition = session.scalars(select(Edition).where(Edition.isbn13 == isbn13)).first()
            if edition is not None:
                return edition.book

    norm_title = normalize_text(title)
    if not norm_title:
        return None
    norm_author = normalize_text(author) if author else None

    # Pass 2: exact normalized title (+ author).
    for book in _iter_books(session, norm_author):
        if normalize_text(book.title) == norm_title:
            return book

    # Pass 3: edition keywords stripped on both sides.
    stripped_query = _strip_edition_keywords(norm_title)
    if stripped_query and stripped_query != norm_title:
        for book in _iter_books(session, norm_author):
            if _strip_edition_keywords(normalize_text(book.title)) == stripped_query:
                return book

    # Pass 4: FTS fallback, author-constrained when known.
    tokens = [t for t in norm_title.split() if t not in STOPWORDS]
    if len(tokens) >= 2:
        return _fts_match(session, tokens, norm_author)
    return None


def _iter_books(session: Session, norm_author: str | None) -> Iterator[Book]:
    if norm_author:
        author_ids = [
            a.id for a in session.scalars(select(Author)) if normalize_text(a.name) == norm_author
        ]
        for author_id in author_ids:
            yield from session.scalars(select(Book).where(Book.author_id == author_id))
    else:
        yield from session.scalars(select(Book))


def _strip_edition_keywords(norm_title: str) -> str | None:
    kept = [w for w in norm_title.split() if w not in EDITION_KEYWORDS and w not in STOPWORDS]
    return " ".join(kept) or None


def _fts_match(session: Session, tokens: list[str], norm_author: str | None) -> Book | None:
    query = " AND ".join(f'"{t}"' for t in tokens)
    rows = session.execute(
        text("SELECT rowid FROM book_fts WHERE book_fts MATCH :q LIMIT 10"),
        {"q": query},
    ).all()

    best: tuple[int, Book] | None = None
    for (book_id,) in rows:
        book = session.get(Book, book_id)
        if book is None:
            continue
        author_mismatch = (
            norm_author is not None
            and book.author is not None
            and normalize_text(book.author.name) != norm_author
        )
        if author_mismatch:
            continue
        book_tokens = {t for t in normalize_text(book.title).split() if t not in STOPWORDS}
        overlap = len(set(tokens) & book_tokens)
        if overlap >= 2 and (best is None or overlap > best[0]):
            best = (overlap, book)
    return best[1] if best else None
