"""Phase 3 — Anna's Archive manual-link indexer + queue handling."""

import respx
from sqlalchemy import select

from libarr.db import session_factory
from libarr.models import Author, Book, Indexer, QueueItem


def _seed_book(session, title="Dune", author="Frank Herbert"):
    a = Author(name=author, monitored=True)
    b = Book(title=title, author=a, monitored=True)
    session.add_all([a, b])
    session.commit()
    return b


def test_annas_search_returns_manual_release():
    from libarr.indexers.annasarchive import AnnasArchiveIndexer

    releases = AnnasArchiveIndexer(name="Anna's Archive").search("Dune Frank Herbert")

    assert len(releases) == 1
    release = releases[0]
    assert release.manual is True
    assert release.download_url.startswith("https://annas-archive.gl/search?q=")
    assert "Dune" in release.download_url
    assert release.page_url == release.download_url


def test_annas_recent_is_empty():
    from libarr.indexers.annasarchive import AnnasArchiveIndexer

    assert AnnasArchiveIndexer(name="Anna's Archive").recent() == []


def test_annas_registered():
    from libarr.indexers.registry import _CLIENTS

    assert "annasarchive" in _CLIENTS


@respx.mock
def test_search_now_with_only_annas_queues_manual(client, db):
    """With only a manual indexer, search-now queues a manual item (no grab)."""
    client, db = client
    with session_factory(db)() as session:
        book = _seed_book(session)
        session.add(Indexer(name="aa", kind="annasarchive"))
        session.commit()
        book_id = book.id

    from libarr.tasks.search import search_now

    with session_factory(db)() as session:
        book = session.get(Book, book_id)
        result = search_now(session, book)

    assert result["queued"] is True
    assert result["manual"] is True
    assert "annas-archive.gl" in result["download_url"]

    with session_factory(db)() as session:
        item = session.scalars(select(QueueItem)).one()
        assert item.manual is True
        assert item.status == "queued"
        assert "annas-archive.gl" in (item.download_url or "")


@respx.mock
def test_process_queue_skips_manual_items(client, db):
    """Manual items must never be pushed to a download client."""
    client, db = client
    with session_factory(db)() as session:
        book = _seed_book(session)
        session.add(
            QueueItem(
                book_id=book.id,
                release_guid="aa:1",
                title="Dune",
                indexer_name="aa",
                download_url="https://annas-archive.gl/search?q=Dune",
                format=None,
                status="queued",
                manual=True,
            )
        )
        session.add(
            Indexer(name="idx", kind="torznab", url="http://idx.example", categories="7000")
        )
        session.commit()

    from libarr.tasks.download_watch import process_queue

    with session_factory(db)() as session:
        stats = process_queue(session)

    assert stats["grabbed"] == 0
    with session_factory(db)() as session:
        item = session.scalars(select(QueueItem)).one()
        assert item.status == "queued"  # untouched, still a bookmark


@respx.mock
def test_queue_api_lists_manual_items(client, db):
    client, db = client
    with session_factory(db)() as session:
        book = _seed_book(session)
        session.add(
            QueueItem(
                book_id=book.id,
                release_guid="aa:2",
                title="Dune",
                indexer_name="aa",
                download_url="https://annas-archive.gl/search?q=Dune",
                format=None,
                status="queued",
                manual=True,
            )
        )
        session.commit()

    queue = client.get("/api/v1/queue").json()
    assert len(queue) == 1
    assert queue[0]["manual"] is True
    assert queue[0]["download_url"].startswith("https://annas-archive.gl/")
