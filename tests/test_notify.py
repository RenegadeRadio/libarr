"""Phase 1.13 — notifications via Apprise."""

import apprise
import respx
from httpx import Response

import libarr.notify as notify_module


def test_notify_noop_without_config(monkeypatch):
    monkeypatch.delenv("LIBARR_APPRISE_URLS", raising=False)
    assert notify_module.configured() is False
    assert notify_module.notify("t", "b") is False


class _FakeApprise:
    def __init__(self):
        self.urls = []
        self.calls = []

    def add(self, url):
        self.urls.append(url)

    def notify(self, body, title):
        self.calls.append((title, body))
        return True


def test_notify_sends_to_configured_services(monkeypatch):
    monkeypatch.setenv("LIBARR_APPRISE_URLS", "ntfy://example.com/topic, tgram://tok/1")
    fake = _FakeApprise()
    monkeypatch.setattr(apprise, "Apprise", lambda: fake)

    assert notify_module.configured() is True
    assert notify_module.notify("Library enriched", "3 books enriched") is True
    assert fake.urls == ["ntfy://example.com/topic", "tgram://tok/1"]
    assert fake.calls == [("Library enriched", "3 books enriched")]


@respx.mock
def test_enrich_library_notifies(monkeypatch, session):
    """The enrichment worker announces its work when notifications are on."""
    from libarr.metadata.enrich import enrich_library
    from libarr.models import Author, Book, Edition

    monkeypatch.setenv("LIBARR_APPRISE_URLS", "ntfy://example.com/topic")
    fake = _FakeApprise()
    monkeypatch.setattr(apprise, "Apprise", lambda: fake)

    respx.get(url__startswith="https://openlibrary.org/api/books").mock(
        return_value=Response(
            200,
            json={
                "ISBN:9780441172719": {
                    "details": {
                        "title": "Dune",
                        "authors": [{"name": "Frank Herbert"}],
                        "subjects": [{"name": "Science fiction"}],
                        "publish_date": "1965",
                        "works": [{"key": "/works/OL123W"}],
                        "isbn_13": ["9780441172719"],
                    }
                }
            },
        )
    )
    respx.get(url__startswith="https://openlibrary.org/works").mock(
        return_value=Response(200, json={"title": "Dune", "subjects": []})
    )

    author = Author(name="Frank Herbert")
    book = Book(title="Dune", author=author)
    session.add(book)
    session.flush()
    session.add(Edition(book_id=book.id, isbn13="9780441172719", format="EPUB"))
    session.commit()

    enrich_library(session)

    assert fake.calls, "expected a notification call"
    assert "enriched" in fake.calls[0][1]
