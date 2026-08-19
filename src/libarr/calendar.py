"""Calendar (Phase 3): recent/upcoming releases for monitored authors.

Open Library's search API gives year granularity, not dates — so the calendar
is honest about it: each monitored author's newest works (first publish year
>= current year - 1) are listed as release events dated at their year.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from libarr.indexers.base import IndexerError
from libarr.indexers.openlibrary import OpenLibraryIndexer
from libarr.models import Author


def calendar_events(session: Session, *, years_back: int = 1) -> list[dict[str, Any]]:
    """Release events for monitored authors: {title, author, year}."""
    authors = session.scalars(
        select(Author).where(Author.monitored.is_(True)).order_by(Author.name)
    ).all()
    if not authors:
        return []
    cutoff = datetime.now(UTC).year - years_back
    indexer = OpenLibraryIndexer(name="Open Library")
    events: list[dict[str, Any]] = []
    for author in authors:
        try:
            releases = indexer.search(f"author:{author.name}", require_download=False)
        except IndexerError:
            continue  # provider isolation
        for release in releases:
            if release.year is None or release.year < cutoff:
                continue
            events.append(
                {
                    "title": release.title,
                    "author": release.author or author.name,
                    "year": release.year,
                    "work_key": release.guid,
                }
            )
    events.sort(key=lambda e: (e["year"], e["author"], e["title"]), reverse=True)
    return events
