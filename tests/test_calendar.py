"""Phase 3 — calendar of releases for monitored authors (Readarr-style)."""

import respx
from httpx import Response

from libarr.db import session_factory
from libarr.models import Author, Book

OL_AUTHOR_SEARCH = {
    "numFound": 2,
    "docs": [
        {
            "key": "/works/OL1W",
            "title": "Dune: Messiah",
            "author_name": ["Frank Herbert"],
            "first_publish_year": 2026,
            "subject": ["Science fiction"],
        },
        {
            "key": "/works/OL2W",
            "title": "Dune",
            "author_name": ["Frank Herbert"],
            "first_publish_year": 1965,
            "subject": ["Science fiction"],
        },
    ],
}


@respx.mock
def test_calendar_lists_recent_works_of_monitored_authors(client, db):
    client, db = client
    with session_factory(db)() as session:
        author = Author(name="Frank Herbert", monitored=True)
        session.add_all([author, Book(title="Dune", author=author, monitored=True)])
        session.commit()

    respx.get(url__startswith="https://openlibrary.org/search.json").mock(
        return_value=Response(200, json=OL_AUTHOR_SEARCH)
    )

    events = client.get("/api/v1/calendar").json()

    # Only works at/after the window start (current year - 1) are listed.
    assert any(e["title"] == "Dune: Messiah" for e in events)
    assert not any(e["title"] == "Dune" for e in events)  # 1965 is ancient
    for event in events:
        assert event["author"] == "Frank Herbert"


def test_calendar_empty_without_monitored_authors(client, db):
    client, db = client
    with session_factory(db)() as session:
        author = Author(name="Ursula K. Le Guin", monitored=False)
        session.add_all([author, Book(title="The Dispossessed", author=author)])
        session.commit()

    events = client.get("/api/v1/calendar").json()
    assert events == []
