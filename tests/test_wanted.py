"""Phase 2.5 — wanted lists, search-now, history, monitor toggles, upgrades."""

import respx
from httpx import Response
from sqlalchemy import select

from libarr.db import session_factory
from libarr.fts import reindex_book
from libarr.models import Author, Book, Edition, File, HistoryEvent, Indexer, QueueItem

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


def _seed_book(session, *, title="Dune", author="Frank Herbert", monitored=True, fmt=None):
    a = Author(name=author, monitored=True)
    b = Book(title=title, author=a, monitored=monitored)
    session.add_all([a, b])
    session.flush()
    edition = Edition(book_id=b.id, isbn13=None, format=fmt or "EPUB")
    session.add(edition)
    session.flush()  # edition.id must exist before attaching File rows
    if fmt:
        session.add(
            File(
                edition_id=edition.id,
                path=f"/tmp/{title}.{fmt.lower()}",
                format=fmt,
                size_bytes=10,
                sha256="a" * 64,
            )
        )
    session.commit()
    reindex_book(session, b.id)
    session.commit()
    return b


def test_wanted_missing_lists_books_without_files(client, db):
    client, db = client
    with session_factory(db)() as session:
        _seed_book(session, title="Dune")
        _seed_book(session, title="The Stand", author="Stephen King", fmt="MOBI")

    missing = client.get("/api/v1/wanted/missing").json()
    assert [m["title"] for m in missing] == ["Dune"]


def test_wanted_cutoff_lists_books_below_cutoff(client, db):
    client, db = client
    with session_factory(db)() as session:
        _seed_book(session, title="Dune", fmt="EPUB")  # at cutoff → not listed
        _seed_book(session, title="The Stand", author="Stephen King", fmt="MOBI")  # below cutoff

    cutoff = client.get("/api/v1/wanted/cutoff").json()
    assert [m["title"] for m in cutoff] == ["The Stand"]


def test_author_monitor_toggle(client, db):
    client, db = client
    with session_factory(db)() as session:
        book = _seed_book(session, monitored=False)
        author_id = book.author_id

    resp = client.patch(f"/api/v1/authors/{author_id}", json={"monitored": True})
    assert resp.status_code == 200
    assert resp.json()["monitored"] is True

    with session_factory(db)() as session:
        assert session.get(Author, author_id).monitored is True


@respx.mock
def test_book_search_now_queues_winner(client, db):
    client, db = client
    with session_factory(db)() as session:
        book = _seed_book(session)
        session.add(
            Indexer(name="idx", kind="torznab", url="http://idx.example", categories="7000")
        )
        session.commit()
        book_id = book.id

    respx.get(url__startswith="http://idx.example/api").mock(return_value=Response(200, text=_RSS))

    resp = client.post(f"/api/v1/books/{book_id}/search")
    assert resp.status_code == 200
    body = resp.json()
    assert body["queued"] is True
    assert body["winner"] == "Dune - Frank Herbert (1965) EPUB"

    with session_factory(db)() as session:
        items = session.scalars(select(QueueItem)).all()
        assert len(items) == 1
        assert items[0].book_id == book_id


def test_history_api_returns_events(client, db):
    client, db = client
    with session_factory(db)() as session:
        book = _seed_book(session)
        session.add(
            HistoryEvent(book_id=book.id, kind="grab", title="Dune - Frank Herbert (1965) EPUB")
        )
        session.add(
            HistoryEvent(
                book_id=book.id, kind="import", title="Dune", details="/data/books/Dune.epub"
            )
        )
        session.commit()

    history = client.get("/api/v1/history").json()
    assert len(history) == 2
    assert history[0]["kind"] == "import"  # newest first
    assert history[1]["kind"] == "grab"

    grabs = client.get("/api/v1/history", params={"kind": "grab"}).json()
    assert len(grabs) == 1


@respx.mock
def test_rss_sync_records_grab_history_and_upgrades(client, db):
    """Books below cutoff get upgraded; grabs are logged in history."""
    client, db = client
    with session_factory(db)() as session:
        _seed_book(session, title="Dune", fmt="MOBI")  # below cutoff → EPUB is an upgrade
        session.add(
            Indexer(name="idx", kind="torznab", url="http://idx.example", categories="7000")
        )
        session.commit()

    respx.get(url__startswith="http://idx.example/api").mock(return_value=Response(200, text=_RSS))

    with session_factory(db)() as session:
        from libarr.tasks.rss import rss_sync

        stats = rss_sync(session)

    assert stats["idx"] == 1  # EPUB queued as upgrade
    with session_factory(db)() as session:
        items = session.scalars(select(QueueItem)).all()
        assert len(items) == 1
        events = session.scalars(select(HistoryEvent)).all()
        assert any(e.kind == "grab" for e in events)


@respx.mock
def test_rss_sync_does_not_requeue_at_cutoff(client, db):
    """A book already at cutoff (EPUB) must not re-grab the same format."""
    client, db = client
    with session_factory(db)() as session:
        _seed_book(session, title="Dune", fmt="EPUB")
        session.add(
            Indexer(name="idx", kind="torznab", url="http://idx.example", categories="7000")
        )
        session.commit()

    respx.get(url__startswith="http://idx.example/api").mock(return_value=Response(200, text=_RSS))

    with session_factory(db)() as session:
        from libarr.tasks.rss import rss_sync

        stats = rss_sync(session)

    assert stats["idx"] == 0
    with session_factory(db)() as session:
        assert session.scalars(select(QueueItem)).first() is None
