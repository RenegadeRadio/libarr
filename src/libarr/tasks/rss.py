"""RSS sync: poll every enabled indexer, queue wanted releases (plan 2.1.3).

Pure and testable: takes a session, returns per-indexer stats. The scheduler
(ARQ/Redis in production, or a manual trigger) owns cadence and cycle jitter —
one dead indexer is isolated here and never blocks the others.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from libarr.acquisition.wanted import match_release
from libarr.indexers.base import IndexerError
from libarr.indexers.registry import build_indexer
from libarr.models import Indexer, QueueItem


def rss_sync(session: Session) -> dict[str, int | str]:
    """Queue releases matching monitored books from every enabled RSS indexer.

    Returns {indexer_name: queued_count | "error"}. Unmatched and duplicate
    releases are skipped; already-owned formats are skipped (no re-grab).
    """
    indexers = session.scalars(
        select(Indexer)
        .where(Indexer.enabled.is_(True), Indexer.rss_enabled.is_(True))
        .order_by(Indexer.priority, Indexer.name)
    ).all()

    stats: dict[str, int | str] = {}
    for row in indexers:
        try:
            client = build_indexer(row)
            releases = client.recent(limit=50)
        except IndexerError:
            stats[row.name] = "error"
            continue

        queued = 0
        for release in releases:
            book = match_release(session, release)
            if book is None:
                continue
            duplicate = session.scalars(
                select(QueueItem).where(QueueItem.release_guid == release.guid)
            ).first()
            if duplicate is not None:
                continue
            session.add(
                QueueItem(
                    book_id=book.id,
                    release_guid=release.guid,
                    title=release.title,
                    indexer_name=row.name,
                    download_url=release.download_url,
                    format=release.format,
                    size_bytes=release.size_bytes,
                )
            )
            queued += 1
        session.commit()
        stats[row.name] = queued
    return stats
