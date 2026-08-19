"""Phase 2.2 — queue processing: grab → watch → import hook."""

import respx
from httpx import Response
from sqlalchemy import select

from libarr.db import session_factory
from libarr.models import Author, Book, DownloadClientRow, Edition, QueueItem
from libarr.tasks.download_watch import process_queue


def _seed_queue_item(session, *, url: str | None = "http://tracker/d/1.torrent", status="queued"):
    author = Author(name="Frank Herbert")
    book = Book(title="Dune", author=author, monitored=True)
    session.add_all([author, book])
    session.flush()
    session.add(Edition(book_id=book.id, isbn13=None, format="EPUB"))
    session.flush()
    item = QueueItem(
        book_id=book.id,
        release_guid="g1",
        title="Dune - Frank Herbert (1965) EPUB",
        indexer_name="idx",
        download_url=url,
        format="EPUB",
        status=status,
    )
    session.add(item)
    session.commit()
    return item


def _add_client(session, *, name="qb", kind="qbittorrent", url="http://qb:8080"):
    row = DownloadClientRow(name=name, kind=kind, url=url, username="u", password="p")
    session.add(row)
    session.commit()
    return row


@respx.mock
def test_process_queue_grabs_and_imports(client, db):
    client, db = client
    with session_factory(db)() as session:
        _seed_queue_item(session)
        _add_client(session)

    respx.post("http://qb:8080/api/v2/auth/login").mock(return_value=Response(200, text="Ok."))
    respx.post("http://qb:8080/api/v2/torrents/add").mock(return_value=Response(200, text="Ok."))
    respx.get("http://qb:8080/api/v2/torrents/info").mock(
        return_value=Response(
            200,
            json=[
                {
                    "hash": "abc",
                    "name": "Dune.epub",
                    "state": "downloading",
                    "progress": 0.1,
                    "size": 10,
                    "save_path": "/downloads",
                }
            ],
        )
    )

    with session_factory(db)() as session:
        stats = process_queue(session)
    assert stats["grabbed"] == 1

    with session_factory(db)() as session:
        item = session.scalars(select(QueueItem)).one()
        assert item.status == "downloading"
        assert item.client_download_id == "abc"
        assert item.client_name == "qb"

    # Next cycle: the torrent finished.
    respx.get("http://qb:8080/api/v2/torrents/info").mock(
        return_value=Response(
            200,
            json=[
                {
                    "hash": "abc",
                    "name": "Dune.epub",
                    "state": "uploading",
                    "progress": 1.0,
                    "size": 10,
                    "save_path": "/downloads",
                }
            ],
        )
    )
    with session_factory(db)() as session:
        stats = process_queue(session)
    assert stats["completed"] == 1

    with session_factory(db)() as session:
        item = session.scalars(select(QueueItem)).one()
        assert item.status == "imported"


@respx.mock
def test_process_queue_calls_import_hook(client, db):
    client, db = client
    with session_factory(db)() as session:
        _seed_queue_item(session, status="downloading", url=None)
        item = session.scalars(select(QueueItem)).one()
        item.client_name = "qb"
        item.client_download_id = "abc"
        session.commit()
        _add_client(session)

    respx.post("http://qb:8080/api/v2/auth/login").mock(return_value=Response(200, text="Ok."))
    respx.get("http://qb:8080/api/v2/torrents/info").mock(
        return_value=Response(
            200,
            json=[
                {
                    "hash": "abc",
                    "name": "Dune.epub",
                    "state": "uploading",
                    "progress": 1.0,
                    "size": 10,
                    "save_path": "/downloads",
                }
            ],
        )
    )

    calls = []

    def hook(session, queue_item, client_item):
        calls.append((queue_item.id, client_item.save_path))

    with session_factory(db)() as session:
        stats = process_queue(session, import_hook=hook)

    assert stats["completed"] == 1
    assert calls == [(1, "/downloads")]


@respx.mock
def test_grab_failure_marks_failed(client, db):
    client, db = client
    with session_factory(db)() as session:
        _seed_queue_item(session)
        _add_client(session)

    respx.post("http://qb:8080/api/v2/auth/login").mock(return_value=Response(200, text="Ok."))
    respx.post("http://qb:8080/api/v2/torrents/add").mock(return_value=Response(500, text="boom"))
    respx.get("http://qb:8080/api/v2/torrents/info").mock(return_value=Response(200, json=[]))

    with session_factory(db)() as session:
        stats = process_queue(session)

    assert stats["failed"] == 1
    with session_factory(db)() as session:
        assert session.scalars(select(QueueItem)).one().status == "failed"


@respx.mock
def test_dead_client_does_not_block_grab(client, db):
    client, db = client
    with session_factory(db)() as session:
        _seed_queue_item(session)
        _add_client(session, name="dead", kind="qbittorrent", url="http://dead:8080")

    respx.post("http://dead:8080/api/v2/auth/login").mock(return_value=Response(500, text="boom"))

    with session_factory(db)() as session:
        stats = process_queue(session)

    assert stats["grabbed"] == 0
    assert stats["failed"] == 1
    with session_factory(db)() as session:
        assert session.scalars(select(QueueItem)).one().status == "failed"


def test_no_clients_configured_is_noop(client, db):
    client, db = client
    with session_factory(db)() as session:
        _seed_queue_item(session)

    with session_factory(db)() as session:
        stats = process_queue(session)

    assert stats == {"grabbed": 0, "completed": 0, "failed": 0}
    with session_factory(db)() as session:
        assert session.scalars(select(QueueItem)).one().status == "queued"
