"""Phase 1.7/1.7b — REST API (authors/books/editions) + genre/keyword search."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from libarr.api.deps import get_session
from libarr.db import session_factory
from libarr.fts import reindex_book
from libarr.main import app
from libarr.models import Author, Book, Edition, File, Subject
from tests.fixtures.make_epub import make_epub


@pytest.fixture()
def client(db, tmp_path):
    def override():
        with session_factory(db)() as s:
            yield s

    app.dependency_overrides[get_session] = override
    with TestClient(app) as test_client:
        yield test_client, db
    app.dependency_overrides.clear()


def _seed_library(session, tmp_path):
    """Two authors, three books (one with subjects + a real epub file)."""
    king = Author(name="Stephen King", sort_name="King, Stephen")
    herbert = Author(name="Frank Herbert")
    session.add_all([king, herbert])
    session.flush()

    stand = Book(author_id=king.id, title="The Stand", year=1990, monitored=True)
    session.add(stand)
    session.flush()
    session.add(Edition(book_id=stand.id, isbn13="9780451169518", format="EPUB"))

    dune = Book(author_id=herbert.id, title="Dune", year=1965, language="eng")
    session.add(dune)
    session.flush()
    session.add(Edition(book_id=dune.id, isbn13="9780441172719", format="EPUB"))
    session.add_all(
        [
            Subject(book_id=dune.id, name="Science Fiction", slug="science-fiction", source="user"),
            Subject(book_id=dune.id, name="Ecology", slug="ecology", source="user"),
        ]
    )

    neuromancer = Book(author_id=None, title="Neuromancer", year=1984, language="eng")
    session.add(neuromancer)
    session.flush()
    session.add(
        Subject(
            book_id=neuromancer.id, name="Science Fiction",
            slug="science-fiction", source="user",
        )
    )

    epub_path = make_epub(tmp_path / "Dune - Frank Herbert.epub", "Dune", "Frank Herbert")
    session.add(
        File(
            edition_id=dune.editions[0].id, path=str(epub_path), format="EPUB",
            size_bytes=epub_path.stat().st_size, sha256="x" * 64,
        )
    )
    session.commit()
    for b in (stand, dune, neuromancer):
        reindex_book(session, b.id)
    session.commit()


def test_list_authors_with_counts(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        _seed_library(session, tmp_path)

    resp = client.get("/api/v1/authors")

    assert resp.status_code == 200
    authors = resp.json()
    assert {a["name"] for a in authors} == {"Stephen King", "Frank Herbert"}
    by_name = {a["name"]: a for a in authors}
    assert by_name["Stephen King"]["book_count"] == 1
    assert by_name["Frank Herbert"]["book_count"] == 1


def test_author_detail_and_404(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        _seed_library(session, tmp_path)
        author_id = session.scalars(select(Author).where(Author.name == "Frank Herbert")).one().id

    resp = client.get(f"/api/v1/authors/{author_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Frank Herbert"
    assert resp.json()["book_count"] == 1

    assert client.get("/api/v1/authors/99999").status_code == 404


def test_list_books_paginated(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        _seed_library(session, tmp_path)

    resp = client.get("/api/v1/books?limit=2&offset=1")
    assert resp.status_code == 200
    books = resp.json()
    assert len(books) == 2
    assert {b["title"] for b in books} == {"Neuromancer", "The Stand"}  # alphabetical

    resp = client.get("/api/v1/books?monitored=true")
    assert [b["title"] for b in resp.json()] == ["The Stand"]


def test_book_detail_includes_editions_subjects(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        _seed_library(session, tmp_path)
        dune_id = session.scalars(
            select(Book).where(Book.title == "Dune")
        ).one().id

    resp = client.get(f"/api/v1/books/{dune_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Dune"
    assert body["author_name"] == "Frank Herbert"
    assert body["subjects"] == ["Ecology", "Science Fiction"]
    assert body["formats"] == ["EPUB"]
    assert body["editions"][0]["isbn13"] == "9780441172719"
    assert body["editions"][0]["files"][0]["path"].endswith("Dune - Frank Herbert.epub")

    assert client.get("/api/v1/books/99999").status_code == 404


def test_book_file_download(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        _seed_library(session, tmp_path)
        dune_id = session.scalars(select(Book).where(Book.title == "Dune")).one().id
        stand_id = session.scalars(select(Book).where(Book.title == "The Stand")).one().id

    resp = client.get(f"/api/v1/books/{dune_id}/file")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/epub")
    assert resp.content.startswith(b"PK")  # zip magic

    # Book whose edition has no file on disk → 404.
    assert client.get(f"/api/v1/books/{stand_id}/file").status_code == 404


def test_patch_book_updates_and_reindexes(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        _seed_library(session, tmp_path)
        stand_id = session.scalars(select(Book).where(Book.title == "The Stand")).one().id

    resp = client.patch(
        f"/api/v1/books/{stand_id}",
        json={"title": "The Stand (Complete)", "year": 1990, "monitored": False},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "The Stand (Complete)"
    assert resp.json()["monitored"] is False

    # FTS reindexed: search finds the new title.
    found = client.get("/api/v1/search", params={"q": "Complete"}).json()
    assert found["total"] == 1
    assert found["results"][0]["title"] == "The Stand (Complete)"


def test_search_keyword(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        _seed_library(session, tmp_path)

    resp = client.get("/api/v1/search", params={"q": "herbert dune"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["results"][0]["title"] == "Dune"


def test_search_genre_filters_and_facets(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        _seed_library(session, tmp_path)

    resp = client.get("/api/v1/search", params={"genre": "science-fiction"})

    body = resp.json()
    titles = {b["title"] for b in body["results"]}
    assert titles == {"Dune", "Neuromancer"}
    assert body["total"] == 2
    # Facets cover all subjects of the filtered set.
    facet_by_slug = {f["slug"]: f for f in body["facets"]}
    assert facet_by_slug["science-fiction"]["count"] == 2
    assert facet_by_slug["ecology"]["count"] == 1


def test_search_year_and_language_filters(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        _seed_library(session, tmp_path)

    resp = client.get(
        "/api/v1/search",
        params={"year_min": 1960, "year_max": 1970, "language": "eng"},
    )
    assert [b["title"] for b in resp.json()["results"]] == ["Dune"]


def test_search_requires_at_least_one_filter(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        _seed_library(session, tmp_path)

    assert client.get("/api/v1/search").status_code == 400
    # Stopword-only queries are treated as no query → 400.
    assert client.get("/api/v1/search", params={"q": "the"}).status_code == 400
