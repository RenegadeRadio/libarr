"""Phase 2.4 — import pipeline: locate → verify → hardlink → name → File row."""

import os
from pathlib import Path

from sqlalchemy import select

from libarr.acquisition.import_pipeline import (
    ImportResult,
    import_download,
    render_template,
)
from libarr.db import session_factory
from libarr.fts import reindex_book
from libarr.models import Author, Book, DownloadClientRow, Edition, File, QueueItem
from tests.fixtures.make_epub import make_epub

TEMPLATE = (
    "{Author Name}/{Series} - {Book Title} ({Release Year})/"
    "{Series} - {Book Title} ({Release Year}) - {Author}.{Extension}"
)


def _seed_book_with_queue(session, *, title="Dune", author="Frank Herbert", year=1965):
    a = Author(name=author)
    b = Book(title=title, author=a, year=year, monitored=True)
    session.add_all([a, b])
    session.flush()
    edition = Edition(book_id=b.id, isbn13=None, format="EPUB")
    session.add(edition)
    session.flush()
    item = QueueItem(
        book_id=b.id,
        release_guid="g1",
        title=f"{title} - {author} ({year}) EPUB",
        indexer_name="idx",
        download_url="http://x/1",
        format="EPUB",
        status="importing",
    )
    session.add(item)
    session.commit()
    reindex_book(session, b.id)
    session.commit()
    return b, item, edition


def _client_item(save_path: str):
    from libarr.clients.base import ClientItem

    return ClientItem(
        id="abc", name="Dune.epub", status="complete", progress=100.0, save_path=save_path
    )


def test_render_template_tokens():
    rendered = render_template(
        TEMPLATE,
        author="Frank Herbert",
        series="Dune Chronicles",
        title="Dune",
        year=1965,
        extension="epub",
    )
    assert rendered == Path(
        "Frank Herbert/Dune Chronicles - Dune (1965)/"
        "Dune Chronicles - Dune (1965) - Frank Herbert.epub"
    )


def test_render_template_handles_missing_tokens():
    rendered = render_template(
        "{Author Name}/{Book Title} ({Release Year}).{Extension}",
        author=None,
        series=None,
        title="Neuromancer",
        year=None,
        extension="PDF",
    )
    assert rendered == Path("Unknown Author/Neuromancer .pdf")


def test_import_hardlinks_into_library(client, db, tmp_path):
    client, db = client
    src_dir = tmp_path / "downloads"
    src_dir.mkdir()
    src = src_dir / "Dune - Frank Herbert (1965).epub"
    make_epub(str(src), title="Dune", author="Frank Herbert")

    with session_factory(db)() as session:
        book, item, edition = _seed_book_with_queue(session)
        session.add(DownloadClientRow(name="qb", kind="qbittorrent", url="http://qb:8080"))
        session.commit()
        client_item = _client_item(str(src_dir))

        result = import_download(
            session, item, client_item, library_root=tmp_path / "library", template=TEMPLATE
        )

    assert isinstance(result, ImportResult)
    assert result.ok is True
    assert result.hardlinked is True
    dest = result.destination
    assert dest.is_file()
    # The hardlink law: same inode, source untouched.
    assert os.stat(dest).st_ino == os.stat(src).st_ino
    assert src.is_file()

    with session_factory(db)() as session:
        file_row = session.scalars(select(File)).one()
        assert file_row.path == str(dest)
        assert file_row.format == "EPUB"
        assert len(file_row.sha256) == 64
        assert session.get(QueueItem, item.id).status == "imported"


def test_import_copy_fallback(client, db, tmp_path, monkeypatch):
    client, db = client
    src_dir = tmp_path / "downloads"
    src_dir.mkdir()
    src = src_dir / "Dune - Frank Herbert (1965).epub"
    make_epub(str(src), title="Dune", author="Frank Herbert")

    def _no_link(*args, **kwargs):
        raise OSError("cross-device link")

    monkeypatch.setattr(os, "link", _no_link)

    with session_factory(db)() as session:
        book, item, edition = _seed_book_with_queue(session)
        session.add(DownloadClientRow(name="qb", kind="qbittorrent", url="http://qb:8080"))
        session.commit()
        result = import_download(
            session,
            item,
            _client_item(str(src_dir)),
            library_root=tmp_path / "library",
            template=TEMPLATE,
        )

    assert result.ok is True
    assert result.hardlinked is False
    assert result.destination.is_file()
    assert os.stat(result.destination).st_ino != os.stat(src).st_ino


def test_import_move_mode_removes_source(client, db, tmp_path):
    client, db = client
    src_dir = tmp_path / "downloads"
    src_dir.mkdir()
    src = src_dir / "Dune - Frank Herbert (1965).epub"
    make_epub(str(src), title="Dune", author="Frank Herbert")

    with session_factory(db)() as session:
        book, item, edition = _seed_book_with_queue(session)
        session.add(DownloadClientRow(name="qb", kind="qbittorrent", url="http://qb:8080"))
        session.commit()
        result = import_download(
            session,
            item,
            _client_item(str(src_dir)),
            library_root=tmp_path / "library",
            template=TEMPLATE,
            mode="move",
        )

    assert result.ok is True
    assert not src.exists()
    assert result.destination.is_file()


def test_import_remote_path_mapping(client, db, tmp_path):
    """Client-side /downloads maps to the library host's real path."""
    client, db = client
    real = tmp_path / "data" / "downloads"
    real.mkdir(parents=True)
    src = real / "Dune - Frank Herbert (1965).epub"
    make_epub(str(src), title="Dune", author="Frank Herbert")

    with session_factory(db)() as session:
        book, item, edition = _seed_book_with_queue(session)
        item.client_name = "qb"  # set by the grab step in the real flow
        session.add(
            DownloadClientRow(
                name="qb",
                kind="qbittorrent",
                url="http://qb:8080",
                remote_path="/downloads",
                local_path=str(real),
            )
        )
        session.commit()
        result = import_download(
            session,
            item,
            _client_item("/downloads"),
            library_root=tmp_path / "library",
            template=TEMPLATE,
        )

    assert result.ok is True
    assert result.destination.is_file()


def test_import_no_file_quarantines(client, db, tmp_path):
    client, db = client
    empty_dir = tmp_path / "downloads"
    empty_dir.mkdir()

    with session_factory(db)() as session:
        book, item, edition = _seed_book_with_queue(session)
        session.add(DownloadClientRow(name="qb", kind="qbittorrent", url="http://qb:8080"))
        session.commit()
        result = import_download(
            session,
            item,
            _client_item(str(empty_dir)),
            library_root=tmp_path / "library",
            template=TEMPLATE,
        )

    assert result.ok is False
    assert (tmp_path / "library" / "quarantine").is_dir()
    with session_factory(db)() as session:
        assert session.get(QueueItem, item.id).status == "failed"


def test_import_opf_verification_rejects_mismatch(client, db, tmp_path):
    """An EPUB whose OPF disagrees with the queued book is quarantined."""
    client, db = client
    src_dir = tmp_path / "downloads"
    src_dir.mkdir()
    src = src_dir / "Wrong Book (1999).epub"
    make_epub(str(src), title="Something Else", author="Someone Else")

    with session_factory(db)() as session:
        book, item, edition = _seed_book_with_queue(session)
        session.add(DownloadClientRow(name="qb", kind="qbittorrent", url="http://qb:8080"))
        session.commit()
        result = import_download(
            session,
            item,
            _client_item(str(src_dir)),
            library_root=tmp_path / "library",
            template=TEMPLATE,
        )

    assert result.ok is False
    assert "mismatch" in (result.error or "").lower() or "quarantin" in (result.error or "").lower()
    with session_factory(db)() as session:
        assert session.get(QueueItem, item.id).status == "failed"
