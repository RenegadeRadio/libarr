"""Phase 2.1.3 — RSS sync: recent releases → match monitored books → queue."""

import respx
from httpx import Response
from sqlalchemy import select

from libarr.db import session_factory
from libarr.fts import reindex_book
from libarr.models import Author, Book, Edition, File, Indexer, QueueItem
from libarr.tasks.rss import rss_sync

_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Dune - Frank Herbert (1965) EPUB</title>
      <guid isPermaLink="false">g1</guid>
      <link>http://tracker.example/d/1</link>
      <pubDate>Fri, 01 Jan 2026 00:00:00 +0000</pubDate>
      <enclosure url="http://tracker.example/d/1.torrent" length="1000"/>
      <torznab:attr name="size" value="1000"/>
      <torznab:attr name="seeders" value="10"/>
    </item>
  </channel>
</rss>"""


def _seed_book(session, title="Dune", author="Frank Herbert", monitored=True):
    a = Author(name=author)
    b = Book(title=title, author=a, monitored=monitored)
    session.add_all([a, b])
    session.flush()
    session.add(Edition(book_id=b.id, isbn13=None, format="EPUB"))
    session.commit()
    reindex_book(session, b.id)
    session.commit()
    return b


@respx.mock
def test_rss_sync_queues_match_for_monitored_book(client, db, monkeypatch):
    client, db = client
    with session_factory(db)() as session:
        book = _seed_book(session)
        session.add(
            Indexer(name="idx", kind="torznab", url="http://idx.example", categories="7000")
        )
        session.commit()

    respx.get(url__startswith="http://idx.example/api").mock(return_value=Response(200, text=_RSS))

    with session_factory(db)() as session:
        stats = rss_sync(session)

    assert stats["idx"] == 1
    with session_factory(db)() as session:
        items = session.scalars(select(QueueItem)).all()
        assert len(items) == 1
        assert items[0].book_id == book.id
        assert items[0].status == "queued"
        assert items[0].release_guid == "g1"


@respx.mock
def test_rss_sync_skips_non_monitored(client, db):
    client, db = client
    with session_factory(db)() as session:
        _seed_book(session, monitored=False)
        session.add(
            Indexer(name="idx", kind="torznab", url="http://idx.example", categories="7000")
        )
        session.commit()

    respx.get(url__startswith="http://idx.example/api").mock(return_value=Response(200, text=_RSS))

    with session_factory(db)() as session:
        stats = rss_sync(session)

    assert stats["idx"] == 0
    with session_factory(db)() as session:
        assert session.scalars(select(QueueItem)).first() is None


@respx.mock
def test_rss_sync_skips_format_already_imported(client, db):
    """A release whose format already exists for the book is not queued."""
    client, db = client
    with session_factory(db)() as session:
        book = _seed_book(session)
        edition = session.scalars(select(Edition).where(Edition.book_id == book.id)).one()
        session.add(
            File(
                edition_id=edition.id,
                path="/tmp/dune.epub",
                format="EPUB",
                size_bytes=10,
                sha256="x" * 64,
            )
        )
        session.add(
            Indexer(name="idx", kind="torznab", url="http://idx.example", categories="7000")
        )
        session.commit()

    respx.get(url__startswith="http://idx.example/api").mock(return_value=Response(200, text=_RSS))

    with session_factory(db)() as session:
        stats = rss_sync(session)

    assert stats["idx"] == 0
    with session_factory(db)() as session:
        assert session.scalars(select(QueueItem)).first() is None


@respx.mock
def test_rss_sync_dedupes_by_guid(client, db):
    client, db = client
    with session_factory(db)() as session:
        _seed_book(session)
        session.add(
            Indexer(name="idx", kind="torznab", url="http://idx.example", categories="7000")
        )
        session.commit()

    respx.get(url__startswith="http://idx.example/api").mock(return_value=Response(200, text=_RSS))

    with session_factory(db)() as session:
        rss_sync(session)
        rss_sync(session)

    with session_factory(db)() as session:
        assert len(session.scalars(select(QueueItem)).all()) == 1


@respx.mock
def test_rss_sync_isolates_dead_indexer(client, db, monkeypatch):
    """One failing indexer never blocks the others."""
    client, db = client
    with session_factory(db)() as session:
        _seed_book(session)
        session.add(
            Indexer(name="dead", kind="torznab", url="http://dead.example", categories="7000")
        )
        session.add(
            Indexer(name="alive", kind="torznab", url="http://alive.example", categories="7000")
        )
        session.commit()

    respx.get(url__startswith="http://dead.example/api").mock(
        return_value=Response(500, text="boom")
    )
    respx.get(url__startswith="http://alive.example/api").mock(
        return_value=Response(200, text=_RSS)
    )

    with session_factory(db)() as session:
        stats = rss_sync(session)

    assert stats["dead"] == "error"
    assert stats["alive"] == 1
    with session_factory(db)() as session:
        assert len(session.scalars(select(QueueItem)).all()) == 1


def test_rss_sync_respects_enabled_flags(client, db):
    client, db = client
    with session_factory(db)() as session:
        _seed_book(session)
        session.add(
            Indexer(
                name="off",
                kind="torznab",
                url="http://off.example",
                categories="7000",
                enabled=False,
            )
        )
        session.add(
            Indexer(
                name="norss",
                kind="torznab",
                url="http://norss.example",
                categories="7000",
                rss_enabled=False,
            )
        )
        session.commit()

    with session_factory(db)() as session:
        stats = rss_sync(session)

    assert stats == {}
