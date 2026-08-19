"""Search-now (plan 2.5.1): query indexers for one book, queue the winner."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from libarr.acquisition.candidates import normalize_candidate
from libarr.acquisition.decision import pick_best
from libarr.acquisition.wanted import DEFAULT_PROFILE
from libarr.history import record
from libarr.indexers.base import IndexerError
from libarr.indexers.registry import build_indexer
from libarr.models import Book, Indexer, QueueItem, User
from libarr.notify import notify


def _user_wants_search_notifications(user: User | None) -> bool:
    """Per-user notification prefs (Phase 3): JSON list of event kinds."""
    if user is None:
        return True  # scheduler/background context: notify by default
    try:
        events = json.loads(user.notify_events or "[]")
    except json.JSONDecodeError:
        events = []
    return "search" in events


def search_now(session: Session, book: Book, *, user: User | None = None) -> dict[str, Any]:
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
        if _user_wants_search_notifications(user):
            notify("Search complete", f"No release found for {book.title}")
        return {"queued": False, "winner": None, "already_queued": False}

    duplicate = session.scalars(
        select(QueueItem).where(QueueItem.release_guid == winner.release.guid)
    ).first()
    if duplicate is not None:
        if _user_wants_search_notifications(user):
            notify("Search complete", f"{book.title} is already queued")
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
            manual=winner.manual,
        )
    )
    record(
        session,
        kind="grab",
        title=winner.release.title,
        book_id=book.id,
        details=f"search-now from {winner.release.indexer_name}"
        + (" (manual download)" if winner.manual else ""),
    )
    session.commit()
    if _user_wants_search_notifications(user):
        notify("Search complete", f"Queued: {winner.release.title}")
    result: dict[str, Any] = {
        "queued": True,
        "winner": winner.release.title,
        "already_queued": False,
    }
    if winner.manual:
        result["manual"] = True
        result["download_url"] = winner.release.download_url
    return result
