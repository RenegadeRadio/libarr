"""Enrichment worker (plan §4.3 flow A): ISBN lookup → rich book records.

For every unenriched book with an ISBN: try Open Library, fall back to
Google Books, then apply the canonical metadata — description, subjects
(genre facets, §4.4), year, publisher, page count, work key — to the ORM
records and rebuild the FTS row. Cached by the resilience layer, so repeat
runs are nearly free and provider outages degrade to stale data.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from libarr.fts import reindex_book
from libarr.metadata.normalize import slugify
from libarr.metadata.providers import BookMetadata, ProviderError
from libarr.metadata.providers.googlebooks import GoogleBooksProvider
from libarr.metadata.providers.openlibrary import OpenLibraryProvider
from libarr.models import Book, Subject
from libarr.notify import notify


def enrich_book(session: Session, book: Book) -> bool:
    """Enrich one book from providers. True when new metadata was applied."""
    if book.work_key or book.description:
        return False  # already enriched

    isbn = next((e.isbn13 for e in book.editions if e.isbn13), None)
    if not isbn:
        return False

    meta: BookMetadata | None = None
    source = ""
    try:
        meta = OpenLibraryProvider(session).lookup_by_isbn(isbn)
        if meta is not None:
            source = "openlibrary"
    except ProviderError:
        pass
    if meta is None:
        try:
            meta = GoogleBooksProvider(session).lookup_by_isbn(isbn)
            if meta is not None:
                source = "googlebooks"
        except ProviderError:
            pass
    if meta is None:
        return False

    _apply(session, book, meta, source)
    session.commit()
    session.refresh(book)  # reload relationships (subjects) added during _apply
    return True


def enrich_library(session: Session) -> int:
    """Enrich every book that is missing metadata; returns the count enriched."""
    books = list(session.scalars(select(Book)))
    enriched = 0
    for book in books:
        if book.work_key or book.description:
            continue
        try:
            enriched += int(enrich_book(session, book))
        except ProviderError:
            continue  # one dead provider must not stall the whole library
    if enriched:
        notify("Library enriched", f"{enriched} book(s) enriched from metadata providers")
    return enriched


def _apply(
    session: Session, book: Book, meta: BookMetadata, source: str
) -> None:
    # Provider data fills gaps; never overwrite user/filename-derived values.
    book.work_key = book.work_key or meta.work_key
    book.description = book.description or meta.description
    book.year = book.year or meta.year
    book.page_count = book.page_count or meta.page_count
    book.language = book.language or meta.language
    book.metadata_json = json.dumps(asdict(meta), ensure_ascii=False)

    if meta.publisher and book.editions:
        edition = book.editions[0]
        if not edition.publisher:
            edition.publisher = meta.publisher

    seen: set[str] = {s.slug for s in book.subjects}
    for subject_name in meta.subjects:
        slug = slugify(subject_name)
        if slug in seen:
            continue  # dedupe across near-identical provider names ("Sci-fi" vs "Science fiction")
        seen.add(slug)
        session.add(Subject(book_id=book.id, name=subject_name, slug=slug, source=source))
    session.flush()
    reindex_book(session, book.id)
