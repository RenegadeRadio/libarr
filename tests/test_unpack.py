"""Phase 3 — archive unpacking in the import pipeline (unpackerr-equivalent)."""

import tarfile
import zipfile
from pathlib import Path

from sqlalchemy import select

from libarr.acquisition.import_pipeline import import_download
from libarr.clients.base import ClientItem
from libarr.db import session_factory
from libarr.models import DownloadClientRow, File, QueueItem
from tests.fixtures.make_epub import make_epub

TEMPLATE = "{Author Name}/{Book Title} ({Release Year}).{Extension}"


def _seed(session, title="Dune", author="Frank Herbert", year=1965):
    from libarr.fts import reindex_book
    from libarr.models import Author, Book, Edition

    a = Author(name=author, monitored=True)
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
    return b, item


def _make_zip(root: Path, epub_name: str = "Dune - Frank Herbert (1965).epub") -> Path:
    src = root / epub_name
    make_epub(str(src), title="Dune", author="Frank Herbert")
    archive = root / "dune-release.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(src, arcname=epub_name)
    src.unlink()  # the payload arrives as a zip, like a torrent release
    return archive


def _make_tar(root: Path, epub_name: str = "Dune - Frank Herbert (1965).epub") -> Path:
    src = root / epub_name
    make_epub(str(src), title="Dune", author="Frank Herbert")
    archive = root / "dune-release.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(src, arcname=epub_name)
    src.unlink()
    return archive


def test_import_unpacks_zip_payload(client, db, tmp_path):
    client, db = client
    dl = tmp_path / "downloads"
    dl.mkdir()
    _make_zip(dl)

    with session_factory(db)() as session:
        book, item = _seed(session)
        session.add(DownloadClientRow(name="qb", kind="qbittorrent", url="http://qb:8080"))
        item.client_name = "qb"
        session.commit()
        result = import_download(
            session,
            item,
            ClientItem(
                id="a",
                name="dune-release.zip",
                status="complete",
                progress=100.0,
                save_path=str(dl),
            ),
            library_root=tmp_path / "library",
            template=TEMPLATE,
        )

    assert result.ok is True, result.error
    assert result.destination.is_file()
    assert result.destination.suffix == ".epub"
    with session_factory(db)() as session:
        file_row = session.scalars(select(File)).one()
        assert file_row.path == str(result.destination)


def test_import_unpacks_tar_payload(client, db, tmp_path):
    client, db = client
    dl = tmp_path / "downloads"
    dl.mkdir()
    _make_tar(dl)

    with session_factory(db)() as session:
        book, item = _seed(session)
        session.add(DownloadClientRow(name="qb", kind="qbittorrent", url="http://qb:8080"))
        item.client_name = "qb"
        session.commit()
        result = import_download(
            session,
            item,
            ClientItem(
                id="a",
                name="dune-release.tar.gz",
                status="complete",
                progress=100.0,
                save_path=str(dl),
            ),
            library_root=tmp_path / "library",
            template=TEMPLATE,
        )

    assert result.ok is True, result.error
    assert result.destination.suffix == ".epub"


def test_import_plain_file_still_works(client, db, tmp_path):
    """Unpacking must not disturb the plain-file path."""
    client, db = client
    dl = tmp_path / "downloads"
    dl.mkdir()
    make_epub(str(dl / "Dune - Frank Herbert (1965).epub"), title="Dune", author="Frank Herbert")

    with session_factory(db)() as session:
        book, item = _seed(session)
        session.add(DownloadClientRow(name="qb", kind="qbittorrent", url="http://qb:8080"))
        item.client_name = "qb"
        session.commit()
        result = import_download(
            session,
            item,
            ClientItem(
                id="a",
                name="Dune - Frank Herbert (1965).epub",
                status="complete",
                progress=100.0,
                save_path=str(dl),
            ),
            library_root=tmp_path / "library",
            template=TEMPLATE,
        )

    assert result.ok is True
    assert result.hardlinked is True
