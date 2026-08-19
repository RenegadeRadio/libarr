"""Phase 2.6 — discovery: subject search, import works, saved lists."""

import respx
from httpx import Response
from sqlalchemy import select

from libarr.db import session_factory
from libarr.discovery import evaluate_lists, import_works, search_works
from libarr.models import Author, Book, DiscoveryList, Subject


def _seed_book(session, title="Dune", author="Frank Herbert"):
    a = Author(name=author)
    b = Book(title=title, author=a, monitored=True)
    session.add_all([a, b])
    session.commit()
    return b


OL_SUBJECT_JSON = {
    "numFound": 3,
    "docs": [
        {
            "key": "/works/OL1W",
            "title": "Dune",
            "author_name": ["Frank Herbert"],
            "first_publish_year": 1965,
            "ia": ["dune0000herb"],
            "subject": ["Science fiction", "Dune (Imaginary place)"],
            "language": ["eng"],
        },
        {
            "key": "/works/OL2W",
            "title": "The Left Hand of Darkness",
            "author_name": ["Ursula K. Le Guin"],
            "first_publish_year": 1969,
            "ia": ["lefthandofdarkne0000legu"],
            "subject": ["Science fiction"],
            "language": ["eng"],
        },
        {
            "key": "/works/OL3W",
            "title": "Neuromancer",
            "author_name": ["William Gibson"],
            "first_publish_year": 1984,
            "ia": ["neuromancer00gibs"],
            "subject": ["Science fiction"],
            "language": ["eng"],
        },
    ],
}


@respx.mock
def test_search_works_filters(client, db):
    client, db = client
    respx.get(url__startswith="https://openlibrary.org/search.json").mock(
        return_value=Response(200, json=OL_SUBJECT_JSON)
    )
    with session_factory(db)() as session:
        works = search_works(session, genre="science fiction", year_min=1970)
    titles = [w.title for w in works]
    assert titles == ["Neuromancer"]  # 1984 ≥ 1970; Dune/Left Hand filtered out


@respx.mock
def test_import_works_creates_books_and_subjects(client, db):
    client, db = client
    respx.get(url__startswith="https://openlibrary.org/search.json").mock(
        return_value=Response(200, json=OL_SUBJECT_JSON)
    )
    with session_factory(db)() as session:
        works = search_works(session, genre="science fiction")
        added = import_works(session, works, monitored=True)

    assert added == 3
    with session_factory(db)() as session:
        books = session.scalars(select(Book)).all()
        assert len(books) == 3
        dune = session.scalars(select(Book).where(Book.title == "Dune")).one()
        assert dune.monitored is True
        assert dune.year == 1965
        subjects = session.scalars(select(Subject).where(Subject.book_id == dune.id)).all()
        assert {s.name for s in subjects} == {"Science fiction", "Dune (Imaginary place)"}


@respx.mock
def test_import_works_dedupes_against_library(client, db):
    client, db = client
    respx.get(url__startswith="https://openlibrary.org/search.json").mock(
        return_value=Response(200, json=OL_SUBJECT_JSON)
    )
    with session_factory(db)() as session:
        _seed_book(session)  # Dune already in the library
    with session_factory(db)() as session:
        works = search_works(session, genre="science fiction")
        added = import_works(session, works)

    assert added == 2  # Dune skipped, Left Hand + Neuromancer added


def test_discovery_list_crud(client, db):
    client, db = client
    created = client.post(
        "/api/v1/discovery-lists",
        json={"name": "New Sci-Fi", "query": {"genre": "science fiction", "year_min": 2020}},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["query"] == {"genre": "science fiction", "year_min": 2020}

    listed = client.get("/api/v1/discovery-lists").json()
    assert len(listed) == 1

    assert client.delete(f"/api/v1/discovery-lists/{body['id']}").status_code == 200
    assert client.get("/api/v1/discovery-lists").json() == []


@respx.mock
def test_evaluate_lists_runs_and_tracks(client, db):
    client, db = client
    respx.get(url__startswith="https://openlibrary.org/search.json").mock(
        return_value=Response(200, json=OL_SUBJECT_JSON)
    )
    with session_factory(db)() as session:
        session.add(
            DiscoveryList(
                name="Sci-Fi 2020s",
                query='{"genre": "science fiction"}',
                max_per_run=10,
                auto_monitor=True,
            )
        )
        session.commit()

    with session_factory(db)() as session:
        stats = evaluate_lists(session)

    assert stats == {"Sci-Fi 2020s": 3}
    with session_factory(db)() as session:
        row = session.scalars(select(DiscoveryList)).one()
        assert row.last_run_at is not None
        books = session.scalars(select(Book)).all()
        assert len(books) == 3
        assert all(b.monitored for b in books)
