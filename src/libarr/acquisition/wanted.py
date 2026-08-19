"""Wanted matching (plan 2.1.3): indexer releases → monitored books."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from libarr.acquisition.parser import parse_book_filename
from libarr.indexers.base import Release, detect_format
from libarr.metadata.matcher import match_book
from libarr.models import Book, File


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


def match_release(session: Session, release: Release) -> Book | None:
    """The monitored book a release belongs to, or None (also skips formats
    the book already owns — upgrades are the decision engine's job, 2.3).

    Release titles are noisy ("Dune - Frank Herbert (1965) EPUB"), so they
    first go through the filename parser — the same pipeline imports use.
    """
    parsed = parse_book_filename(normalize_release_title(release.title))
    title = parsed.title if parsed and parsed.title else release.title
    author = parsed.author if parsed else release.author

    book = match_book(session, title=title, author=author)
    if book is None or not book.monitored:
        return None
    if book_has_format(session, book, release.format):
        return None
    return book
