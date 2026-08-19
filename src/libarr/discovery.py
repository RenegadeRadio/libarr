"""Discovery (plan 2.6): provider subject search → works → import into library."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from libarr.history import record
from libarr.indexers.base import IndexerError
from libarr.indexers.openlibrary import OpenLibraryIndexer
from libarr.metadata.normalize import normalize_text
from libarr.metadata.providers.googlebooks import GoogleBooksProvider
from libarr.metadata.subjects import subject_slug
from libarr.models import Author, Book, DiscoveryList, Subject


@dataclass(slots=True)
class DiscoveryWork:
    title: str
    author: str | None
    year: int | None
    subjects: list[str]
    source: str
    source_key: str


def _dedupe(works: list[DiscoveryWork]) -> list[DiscoveryWork]:
    seen: set[tuple[str, str]] = set()
    out: list[DiscoveryWork] = []
    for work in works:
        key = (normalize_text(work.title), normalize_text(work.author or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(work)
    return out


def search_works(
    session: Session,
    *,
    q: str | None = None,
    genre: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    language: str | None = None,
    limit: int = 50,
) -> list[DiscoveryWork]:
    """Discovery query: Open Library `subject:` search, Google Books fallback."""
    works: list[DiscoveryWork] = []
    if genre:
        try:
            releases = OpenLibraryIndexer(name="Open Library").search_subject(
                genre,
                year_min=year_min,
                year_max=year_max,
                language=language,
                limit=limit,
            )
        except IndexerError:
            releases = []
        for release in releases:
            if year_min is not None and release.year is not None and release.year < year_min:
                continue
            if year_max is not None and release.year is not None and release.year > year_max:
                continue
            works.append(
                DiscoveryWork(
                    title=release.title,
                    author=release.author,
                    year=release.year,
                    subjects=release.subjects,
                    source="openlibrary",
                    source_key=release.guid,
                )
            )
    if not works and q:
        try:
            provider = GoogleBooksProvider(session)
            query = f"subject:{genre} {q}".strip() if genre else q
            metas = provider.search(query)
        except Exception:  # noqa: BLE001 — provider isolation
            metas = []
        for meta in metas:
            works.append(
                DiscoveryWork(
                    title=meta.title or "",
                    author=meta.authors[0] if meta.authors else None,
                    year=meta.year,
                    subjects=meta.subjects or [],
                    source="googlebooks",
                    source_key=meta.work_key or "",
                )
            )
    return _dedupe(works)


def import_works(session: Session, works: list[DiscoveryWork], *, monitored: bool = True) -> int:
    """Add discovered works to the library (deduped). Returns count added."""
    existing = {
        (normalize_text(b.title), normalize_text(b.author.name if b.author else ""))
        for b in session.scalars(select(Book)).all()
    }
    added = 0
    for work in works:
        key = (normalize_text(work.title), normalize_text(work.author or ""))
        if key in existing:
            continue
        author = None
        if work.author:
            author = session.scalars(select(Author).where(Author.name == work.author)).first()
            if author is None:
                author = Author(name=work.author)
                session.add(author)
                session.flush()
        book = Book(title=work.title, author=author, year=work.year, monitored=monitored)
        session.add(book)
        session.flush()
        seen_slugs: set[str] = set()
        for subject_name in work.subjects[:5]:
            slug = subject_slug(subject_name)
            if slug in seen_slugs:
                continue  # "Fantasy" + "Fantasy fiction" → one row
            seen_slugs.add(slug)
            session.add(
                Subject(
                    book_id=book.id,
                    name=subject_name,
                    slug=slug,
                    source=work.source,
                )
            )
        existing.add(key)
        added += 1
    if added:
        record(
            session,
            kind="discovery",
            title=f"{added} new work(s) added",
            details=", ".join(w.title for w in works[:5]),
        )
    session.commit()
    return added


def evaluate_lists(session: Session) -> dict[str, int | str]:
    """Run every enabled discovery list (plan 2.6.4); returns per-list stats."""
    lists = session.scalars(select(DiscoveryList).where(DiscoveryList.enabled.is_(True))).all()
    stats: dict[str, int | str] = {}
    for discovery_list in lists:
        try:
            query = json.loads(discovery_list.query)
        except json.JSONDecodeError:
            stats[discovery_list.name] = "error"
            continue
        works = search_works(session, limit=discovery_list.max_per_run, **query)
        added = import_works(session, works, monitored=discovery_list.auto_monitor)
        discovery_list.last_run_at = datetime.now(UTC).replace(tzinfo=None)
        stats[discovery_list.name] = added
    session.commit()
    return stats
