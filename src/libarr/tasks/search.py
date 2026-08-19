"""Search-now (plan 2.5.1): query indexers for one book, queue the winner."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from libarr.acquisition.candidates import normalize_candidate
from libarr.acquisition.decision import pick_best
from libarr.acquisition.wanted import DEFAULT_PROFILE
from libarr.history import record
from libarr.indexers.base import IndexerError
from libarr.indexers.registry import build_indexer
from libarr.models import Book, Indexer, QueueItem


def search_now(session: Session, book: Book) -> dict[str, Any]:
    """Search every enabled indexer for the book and queue the best release.

    Returns {"queued": bool, "winner": title | None, "already_queued": bool}.
    """
    author = book.author.name if book.author else ""
    query = f"{book.title} {author}".strip()

    indexers = session.scalars(select(Indexer).where(Indexer.enabled.is_(True))).all()
    candidates = []
    for row in indexers:
        try:
            client = build_indexer(row)
            releases = client.search(query)
        except IndexerError:
            continue  # per-indexer isolation
        for release in releases:
            candidate = normalize_candidate(release, indexer_priority=row.priority)
            if candidate is not None:
                candidates.append(candidate)

    winner = pick_best(candidates, DEFAULT_PROFILE)
    if winner is None:
        return {"queued": False, "winner": None, "already_queued": False}

    duplicate = session.scalars(
        select(QueueItem).where(QueueItem.release_guid == winner.release.guid)
    ).first()
    if duplicate is not None:
        return {"queued": False, "winner": winner.release.title, "already_queued": True}

    session.add(
        QueueItem(
            book_id=book.id,
            release_guid=winner.release.guid,
            title=winner.release.title,
            indexer_name=winner.release.indexer_name,
            download_url=winner.release.download_url,
            format=winner.fmt,
            size_bytes=winner.release.size_bytes,
        )
    )
    record(
        session,
        kind="grab",
        title=winner.release.title,
        book_id=book.id,
        details=f"search-now from {winner.release.indexer_name}",
    )
    session.commit()
    return {"queued": True, "winner": winner.release.title, "already_queued": False}
