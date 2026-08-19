"""Phase 1.9/1.10 — reading progress tracking + cover serving."""

import json

import respx
from httpx import Response

from libarr.db import session_factory
from libarr.models import Author, Book, Edition, File
from tests.fixtures.make_epub import make_epub

JPEG_BYTES = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def _seed(session, tmp_path, cover_bytes=None, cover_url=None):
    author = Author(name="Frank Herbert")
    book = Book(title="Dune", author=author, year=1965, language="eng")
    session.add(book)
    session.flush()
    edition = Edition(book_id=book.id, isbn13="9780441172719", format="EPUB")
    session.add(edition)
    session.flush()
    epub_path = make_epub(
        tmp_path / "Dune.epub", "Dune", "Frank Herbert", cover_bytes=cover_bytes
    )
    session.add(
        File(
            edition_id=edition.id, path=str(epub_path), format="EPUB",
            size_bytes=epub_path.stat().st_size, sha256="z" * 64,
        )
    )
    if cover_url:
        book.metadata_json = json.dumps({"cover_url": cover_url})
    session.commit()
    return book


def test_progress_put_and_get_roundtrip(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        book = _seed(session, tmp_path)

    put = client.put(
        f"/api/v1/books/{book.id}/progress",
        json={"profile": "kobo", "position": 0.42, "location": "epubcfi(/6/4)"},
    )
    assert put.status_code == 200
    assert put.json()["position"] == 0.42

    get = client.get(f"/api/v1/books/{book.id}/progress", params={"profile": "kobo"})
    assert get.status_code == 200
    body = get.json()
    assert body["position"] == 0.42
    assert body["location"] == "epubcfi(/6/4)"

    # Different profile → independent progress.
    other = client.get(f"/api/v1/books/{book.id}/progress", params={"profile": "default"})
    assert other.status_code == 404


def test_progress_upsert_overwrites(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        book = _seed(session, tmp_path)

    client.put(
        f"/api/v1/books/{book.id}/progress",
        json={"profile": "default", "position": 0.1},
    )
    client.put(
        f"/api/v1/books/{book.id}/progress",
        json={"profile": "default", "position": 0.9},
    )

    body = client.get(
        f"/api/v1/books/{book.id}/progress", params={"profile": "default"}
    ).json()
    assert body["position"] == 0.9


def test_progress_rejects_out_of_range(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        book = _seed(session, tmp_path)

    resp = client.put(
        f"/api/v1/books/{book.id}/progress",
        json={"profile": "default", "position": 1.5},
    )
    assert resp.status_code == 422


def test_cover_extracted_from_epub(client, tmp_path, monkeypatch):
    monkeypatch.setenv("LIBARR_DATA_DIR", str(tmp_path / "data"))
    client, db = client
    with session_factory(db)() as session:
        _seed(session, tmp_path, cover_bytes=JPEG_BYTES)

    resp = client.get("/api/v1/covers/1")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content == JPEG_BYTES

    # Cached on disk now — second hit served from cache.
    assert (tmp_path / "data" / "covers" / "1.jpg").exists()


@respx.mock
def test_cover_downloaded_from_provider(client, tmp_path, monkeypatch):
    monkeypatch.setenv("LIBARR_DATA_DIR", str(tmp_path / "data"))
    respx.get("https://covers.openlibrary.org/b/id/12345-L.jpg").mock(
        return_value=Response(200, content=JPEG_BYTES)
    )
    client, db = client
    with session_factory(db)() as session:
        _seed(
            session, tmp_path,
            cover_url="https://covers.openlibrary.org/b/id/12345-L.jpg",
        )

    resp = client.get("/api/v1/covers/1")

    assert resp.status_code == 200
    assert resp.content == JPEG_BYTES
    assert (tmp_path / "data" / "covers" / "1.jpg").exists()


def test_cover_missing_returns_404(client, tmp_path, monkeypatch):
    monkeypatch.setenv("LIBARR_DATA_DIR", str(tmp_path / "data"))
    client, db = client
    with session_factory(db)() as session:
        _seed(session, tmp_path)  # no cover, no provider URL, no file cover

    assert client.get("/api/v1/covers/1").status_code == 404
