"""Portable metadata export/import."""

import json
import zipfile
from datetime import date

import pytest
from sqlalchemy import select

from libarr.metadata.backup import MetadataArchiveError, import_archive, write_export
from libarr.models import Author, Book, Edition, File, QueueItem, Subject


def _catalog(session):
    author = Author(name="Ursula K. Le Guin", ol_key="/authors/OL1A", monitored=True)
    book = Book(title="A Wizard of Earthsea", author=author, work_key="/works/OL1W")
    edition = Edition(
        book=book,
        isbn13="9780547773742",
        published_at=date(2012, 9, 11),
        format="EPUB",
    )
    session.add_all(
        [
            author,
            book,
            edition,
            File(
                edition=edition,
                path="/books/earthsea.epub",
                format="EPUB",
                size_bytes=42,
                sha256="a" * 64,
            ),
            Subject(book=book, name="Fantasy", slug="fantasy", source="openlibrary"),
        ]
    )
    session.commit()


def test_json_export_contains_portable_catalog(session, tmp_path):
    _catalog(session)
    output = tmp_path / "metadata.json"

    counts = write_export(session, output)
    payload = json.loads(output.read_text())

    assert payload["format"] == "libarr-metadata"
    assert payload["version"] == 1
    assert counts["books"] == 1
    assert payload["tables"]["editions"][0]["published_at"] == "2012-09-11"
    assert "users" not in payload["tables"]
    assert "download_clients" not in payload["tables"]


def test_zip_export_and_round_trip(session, db, tmp_path):
    _catalog(session)
    output = tmp_path / "metadata.zip"
    write_export(session, output)
    with zipfile.ZipFile(output) as archive:
        assert archive.namelist() == ["metadata.json"]

    for model in (Subject, File, Edition, Book, Author):
        session.query(model).delete()
    session.commit()

    counts = import_archive(session, output)

    assert counts["books"] == 1
    restored = session.scalars(select(Book)).one()
    assert restored.title == "A Wizard of Earthsea"
    assert restored.author.name == "Ursula K. Le Guin"
    assert restored.editions[0].published_at == date(2012, 9, 11)
    assert restored.subjects[0].slug == "fantasy"


def test_import_refuses_nonempty_catalog_without_replace(session, tmp_path):
    _catalog(session)
    output = tmp_path / "metadata.json"
    write_export(session, output)

    with pytest.raises(MetadataArchiveError, match="not empty"):
        import_archive(session, output)


def test_import_replace_is_idempotent(session, tmp_path):
    _catalog(session)
    output = tmp_path / "metadata.json"
    write_export(session, output)
    book = session.scalars(select(Book)).one()
    session.add(
        QueueItem(
            book_id=book.id,
            release_guid="transient-item",
            title=book.title,
            indexer_name="test",
        )
    )
    session.commit()

    import_archive(session, output, replace=True)
    import_archive(session, output, replace=True)

    assert len(session.scalars(select(Book)).all()) == 1
    assert session.scalars(select(QueueItem)).all() == []


def test_import_rejects_wrong_format(session, tmp_path):
    source = tmp_path / "bad.json"
    source.write_text('{"format":"something-else","version":1,"tables":{}}')

    with pytest.raises(MetadataArchiveError, match="not a Libarr"):
        import_archive(session, source)


def test_export_refuses_overwrite(session, tmp_path):
    output = tmp_path / "metadata.json"
    output.write_text("keep me")

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_export(session, output)

    assert output.read_text() == "keep me"
