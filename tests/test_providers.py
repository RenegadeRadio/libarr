"""Phase 1.4 — metadata providers (Open Library, Google Books) + resilient cache."""

import pytest
import respx
from httpx import Response

from libarr.metadata.cache import cached_fetch
from libarr.metadata.providers import ProviderError
from libarr.metadata.providers.googlebooks import GoogleBooksProvider
from libarr.metadata.providers.openlibrary import OpenLibraryProvider

OL_DETAILS = {
    "ISBN:9780441172719": {
        "bib_key": "ISBN:9780441172719",
        "details": {
            "title": "Dune",
            "subtitle": "The first volume of the Dune chronicles",
            "authors": [{"name": "Frank Herbert", "key": "/authors/OL123A"}],
            "subjects": [
                {"name": "Science fiction", "url": "https://openlibrary.org/subjects/science_fiction"},
                {"name": "Dune (Imaginary place)", "url": "https://openlibrary.org/subjects/dune_(imaginary_place)"},
            ],
            "covers": [12345],
            "publish_date": "1965",
            "publishers": [{"name": "Chilton Books"}],
            "number_of_pages": 535,
            "works": [{"key": "/works/OL123W"}],
            "isbn_13": ["9780441172719"],
        },
    }
}

OL_SEARCH = {
    "docs": [
        {
            "key": "/works/OL148829W",
            "title": "Dune",
            "author_name": ["Frank Herbert"],
            "first_publish_year": 1965,
            "subject": ["Science fiction", "Dune (Imaginary place)"],
            "isbn": ["9780441172719"],
            "cover_i": 12345,
        },
        {
            "key": "/works/OL148830W",
            "title": "Dune Messiah",
            "author_name": ["Frank Herbert"],
            "first_publish_year": 1969,
        },
    ]
}

GOOGLE_VOLUMES = {
    "totalItems": 1,
    "items": [
        {
            "volumeInfo": {
                "title": "Dune",
                "authors": ["Frank Herbert"],
                "description": "Set on the desert planet Arrakis.",
                "categories": ["Science Fiction", "Fiction"],
                "publishedDate": "1965-08",
                "publisher": "Chilton Books",
                "pageCount": 535,
                "language": "en",
                "imageLinks": {"thumbnail": "http://books.google.com/thumb.jpg"},
                "industryIdentifiers": [
                    {"type": "ISBN_13", "identifier": "9780441172719"}
                ],
            }
        }
    ]
}


@respx.mock
def test_ol_lookup_by_isbn_normalizes(session):
    respx.get(url__startswith="https://openlibrary.org/api/books").mock(
        return_value=Response(200, json=OL_DETAILS)
    )

    meta = OpenLibraryProvider(session).lookup_by_isbn("9780441172719")

    assert meta.title == "Dune"
    assert meta.authors == ["Frank Herbert"]
    assert meta.subjects == ["Science fiction", "Dune (Imaginary place)"]
    assert meta.year == 1965
    assert meta.publisher == "Chilton Books"
    assert meta.page_count == 535
    assert meta.work_key == "OL123W"
    assert meta.cover_url == "https://covers.openlibrary.org/b/id/12345-L.jpg"
    assert meta.isbn13 == "9780441172719"


@respx.mock
def test_ol_lookup_unknown_isbn_returns_none(session):
    respx.get(url__startswith="https://openlibrary.org/api/books").mock(
        return_value=Response(200, json={})
    )

    assert OpenLibraryProvider(session).lookup_by_isbn("9780000000000") is None


@respx.mock
def test_ol_search_returns_candidates(session):
    respx.get(url__startswith="https://openlibrary.org/search.json").mock(
        return_value=Response(200, json=OL_SEARCH)
    )

    results = OpenLibraryProvider(session).search("dune frank herbert")

    assert len(results) == 2
    assert results[0].title == "Dune"
    assert results[0].subjects == ["Science fiction", "Dune (Imaginary place)"]
    assert results[0].year == 1965
    assert results[0].cover_url == "https://covers.openlibrary.org/b/id/12345-L.jpg"


@respx.mock
def test_google_categories_become_subjects(session):
    respx.get(url__startswith="https://www.googleapis.com/books").mock(
        return_value=Response(200, json=GOOGLE_VOLUMES)
    )

    meta = GoogleBooksProvider(session).lookup_by_isbn("9780441172719")

    assert meta.title == "Dune"
    assert meta.subjects == ["Science Fiction", "Fiction"]
    assert meta.year == 1965
    assert meta.isbn13 == "9780441172719"


@respx.mock
def test_http_error_raises_provider_error(session):
    respx.get(url__startswith="https://openlibrary.org/api/books").mock(
        return_value=Response(500, text="boom")
    )

    with pytest.raises(ProviderError):
        OpenLibraryProvider(session).lookup_by_isbn("9780441172719")


def test_cache_hit_avoids_refetch(session):
    calls = {"n": 0}

    def fetcher() -> dict:
        calls["n"] += 1
        return {"title": "Dune"}

    first = cached_fetch(session, "openlibrary", "isbn", "9780441172719", fetcher)
    second = cached_fetch(session, "openlibrary", "isbn", "9780441172719", fetcher)

    assert first == {"title": "Dune"}
    assert second == {"title": "Dune"}
    assert calls["n"] == 1


def test_cache_stale_while_error(session):
    from datetime import timedelta

    cached_fetch(
        session, "openlibrary", "isbn", "9780441172719", lambda: {"title": "Dune"}
    )

    def broken() -> dict:
        raise ProviderError("provider down")

    # TTL expired → fetcher runs and fails → stale payload is served anyway.
    assert cached_fetch(
        session, "openlibrary", "isbn", "9780441172719", broken,
        ttl=timedelta(seconds=-1),
    ) == {"title": "Dune"}


def test_cache_no_stale_re_raises(session):
    def broken() -> dict:
        raise ProviderError("provider down")

    with pytest.raises(ProviderError):
        cached_fetch(session, "openlibrary", "isbn", "9780441172719", broken)
