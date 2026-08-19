"""Wanted matching (plan 2.1.3/2.5): indexer releases → monitored books."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from libarr.acquisition.parser import parse_book_filename
from libarr.acquisition.quality import QualityProfile, format_score, is_upgrade
from libarr.indexers.base import Release, detect_format
from libarr.metadata.matcher import match_book
from libarr.models import Book, File

DEFAULT_PROFILE = QualityProfile()


def normalize_release_title(title: str) -> str:
    """Give the parser what it needs: a dot-extension.

    Release titles say "Dune - Frank Herbert (1965) EPUB" (no dot); the
    filename parser requires "…(1965).epub". Bare trailing format tokens are
    rewritten to real extensions so the full parser (ISBN/year/series) applies.
    """
    fmt = detect_format(title)
    if fmt is None or re.search(r"\.\w+$", title):
        return title
    words = title.split()
    if words and words[-1].upper() == fmt:
        title = " ".join(words[:-1])
    return f"{title}.{fmt.lower()}"


def book_has_format(session: Session, book: Book, fmt: str | None) -> bool:
    """True when the book already has an imported file in that format."""
    if not fmt:
        return False
    edition_ids = [e.id for e in book.editions]
    if not edition_ids:
        return False
    existing = session.scalars(
        select(File.format).where(File.edition_id.in_(edition_ids), File.format == fmt)
    ).first()
    return existing is not None


def best_imported_format(session: Session, book: Book) -> str | None:
    """The highest-scoring format the book already owns (None if no files)."""
    edition_ids = [e.id for e in book.editions]
    if not edition_ids:
        return None
    formats = session.scalars(select(File.format).where(File.edition_id.in_(edition_ids))).all()
    return max(formats, key=lambda f: format_score(DEFAULT_PROFILE, f), default=None)


def wanted_missing(session: Session) -> list[Book]:
    """Monitored books with no imported file at all (plan 2.5.1)."""
    books = session.scalars(select(Book).where(Book.monitored.is_(True))).all()
    return [b for b in books if best_imported_format(session, b) is None]


def wanted_cutoff(session: Session) -> list[Book]:
    """Monitored books whose best file is below the profile cutoff."""
    from libarr.acquisition.quality import meets_cutoff

    books = session.scalars(select(Book).where(Book.monitored.is_(True))).all()
    result = []
    for book in books:
        best = best_imported_format(session, book)
        if best is not None and not meets_cutoff(best, DEFAULT_PROFILE):
            result.append(book)
    return result


def match_release(session: Session, release: Release) -> Book | None:
    """The monitored book a release belongs to, or None.

    Skips formats the book already owns UNLESS the release is a genuine
    upgrade (beats the current file and the current file is below cutoff —
    plan 2.5.4).
    """
    parsed = parse_book_filename(normalize_release_title(release.title))
    title = parsed.title if parsed and parsed.title else release.title
    author = parsed.author if parsed else release.author

    book = match_book(session, title=title, author=author)
    if book is None or not book.monitored:
        return None
    if book_has_format(session, book, release.format):
        current = best_imported_format(session, book)
        if not is_upgrade(
            current_format=current,
            candidate_format=release.format,
            profile=DEFAULT_PROFILE,
        ):
            return None
    return book
