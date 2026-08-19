"""Phase 3 — request flow (Overseerr-style: request → add → search)."""

import respx
from httpx import Response
from sqlalchemy import select

from libarr.db import session_factory
from libarr.models import Book, HistoryEvent, Indexer, QueueItem

_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Dune - Frank Herbert (1965) EPUB</title>
      <guid isPermaLink="false">g1</guid>
      <link>http://tracker.example/d/1</link>
      <enclosure url="http://tracker.example/d/1.torrent" length="1000"/>
      <torznab:attr name="size" value="1000"/>
      <torznab:attr name="seeders" value="10"/>
    </item>
  </channel>
</rss>"""

OL_BOOKS = {
    "ISBN:9780441013593": {
        "details": {
            "title": "Dune",
            "publish_date": "2005",
            "works": [{"key": "/works/OL1W"}],
            "publishers": ["Ace Books"],
        }
    }
}

OL_WORK = {
    "title": "Dune",
    "subjects": ["Science fiction"],
    "authors": [{"author": {"key": "/authors/OL2A"}}],
    "first_publish_date": "1965",
}

OL_AUTHOR = {"key": "/authors/OL2A", "name": "Frank Herbert"}


@respx.mock
def test_request_by_isbn_adds_and_searches(client, db):
    client, db = client
    with session_factory(db)() as session:
        session.add(
            Indexer(name="idx", kind="torznab", url="http://idx.example", categories="7000")
        )
        session.commit()

    respx.get("https://openlibrary.org/api/books").mock(return_value=Response(200, json=OL_BOOKS))
    respx.get("https://openlibrary.org/works/OL1W.json").mock(
        return_value=Response(200, json=OL_WORK)
    )
    respx.get("https://openlibrary.org/authors/OL2A.json").mock(
        return_value=Response(200, json=OL_AUTHOR)
    )
    respx.get(url__startswith="http://idx.example/api").mock(return_value=Response(200, text=_RSS))

    resp = client.post(
        "/api/v1/requests",
        json={"title": "Dune", "isbn": "9780441013593"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["queued"] is True

    with session_factory(db)() as session:
        book = session.scalars(select(Book).where(Book.title == "Dune")).one()
        assert book.monitored is True
        assert book.year == 2005  # edition publish date through the provider
        assert session.scalars(select(QueueItem)).first() is not None
        kinds = {e.kind for e in session.scalars(select(HistoryEvent)).all()}
        assert "request" in kinds
        assert "grab" in kinds


@respx.mock
def test_request_by_title_uses_discovery(client, db):
    client, db = client
    with session_factory(db)() as session:
        session.add(
            Indexer(name="idx", kind="torznab", url="http://idx.example", categories="7000")
        )
        session.commit()

    ol_json = {
        "numFound": 1,
        "docs": [
            {
                "key": "/works/OL9W",
                "title": "The Left Hand of Darkness",
                "author_name": ["Ursula K. Le Guin"],
                "first_publish_year": 1969,
                "subject": ["Science fiction"],
            }
        ],
    }
    respx.get(url__startswith="https://openlibrary.org/search.json").mock(
        return_value=Response(200, json=ol_json)
    )
    respx.get(url__startswith="http://idx.example/api").mock(return_value=Response(200, text=_RSS))

    resp = client.post(
        "/api/v1/requests",
        json={"title": "The Left Hand of Darkness"},
    )
    assert resp.status_code == 200, resp.text

    with session_factory(db)() as session:
        book = session.scalars(select(Book)).one()
        assert book.title == "The Left Hand of Darkness"
        assert book.monitored is True


def test_request_unresolvable_returns_404(client, db):
    client, db = client
    resp = client.post(
        "/api/v1/requests",
        json={"title": "Nonexistent Book XYZ"},
    )
    assert resp.status_code == 404
