"""Phase 1.6 — enrichment: ISBN lookup → description/subjects/cover/series."""

import json

import respx
from httpx import Response

from libarr.metadata.enrich import enrich_book, enrich_library
from libarr.models import Author, Book, Edition

OL_DETAILS = {
    "ISBN:9780441172719": {
        "details": {
            "title": "Dune",
            "authors": [{"name": "Frank Herbert"}],
            "subjects": [{"name": "Science fiction"}],
            "covers": [12345],
            "publish_date": "1965",
            "publishers": [{"name": "Chilton Books"}],
            "number_of_pages": 535,
            "works": [{"key": "/works/OL123W"}],
            "isbn_13": ["9780441172719"],
        }
    }
}

OL_DETAILS_SECOND_ISBN = {
    "ISBN:9780306406157": {
        "details": {
            "title": "Dune Messiah",
            "authors": [{"name": "Frank Herbert"}],
            "subjects": [{"name": "Science fiction"}],
            "covers": [12345],
            "publish_date": "1969",
            "publishers": [{"name": "Chilton Books"}],
            "number_of_pages": 256,
            "works": [{"key": "/works/OL999W"}],
            "isbn_13": ["9780306406157"],
        }
    }
}

GOOGLE_VOLUMES = {
    "totalItems": 1,
    "items": [
        {
            "volumeInfo": {
                "title": "Dune",
                "authors": ["Frank Herbert"],
                "description": "Set on the desert planet Arrakis.",
                "categories": ["Science Fiction"],
                "publishedDate": "1965",
                "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780441172719"}],
            }
        }
    ]
}


def _book_with_isbn(session, isbn="9780441172719"):
    author = Author(name="Frank Herbert")
    book = Book(title="Dune", author=author)
    session.add(book)
    session.flush()
    session.add(Edition(book_id=book.id, isbn13=isbn, format="EPUB"))
    session.commit()
    return book


@respx.mock
def test_enrich_book_populates_metadata(session):
    respx.get(url__startswith="https://openlibrary.org/api/books").mock(
        return_value=Response(200, json=OL_DETAILS)
    )
    book = _book_with_isbn(session)

    assert enrich_book(session, book) is True

    assert book.description is None or book.work_key == "OL123W"
    assert book.work_key == "OL123W"
    assert book.year == 1965
    assert book.page_count == 535
    assert book.editions[0].publisher == "Chilton Books"
    assert book.metadata_json is not None
    assert json.loads(book.metadata_json)["title"] == "Dune"

    subjects = book.subjects
    assert len(subjects) == 1
    assert subjects[0].name == "Science fiction"
    assert subjects[0].slug == "science-fiction"
    assert subjects[0].source == "openlibrary"


@respx.mock
def test_enrich_falls_back_to_google(session):
    respx.get(url__startswith="https://openlibrary.org/api/books").mock(
        return_value=Response(200, json={})
    )
    respx.get(url__startswith="https://www.googleapis.com/books").mock(
        return_value=Response(200, json=GOOGLE_VOLUMES)
    )
    book = _book_with_isbn(session)

    assert enrich_book(session, book) is True
    assert book.description == "Set on the desert planet Arrakis."
    assert book.subjects[0].source == "googlebooks"


@respx.mock
def test_enrich_both_providers_miss(session):
    respx.get(url__startswith="https://openlibrary.org/api/books").mock(
        return_value=Response(200, json={})
    )
    respx.get(url__startswith="https://www.googleapis.com/books").mock(
        return_value=Response(200, json={"totalItems": 0})
    )
    book = _book_with_isbn(session)

    assert enrich_book(session, book) is False
    assert book.work_key is None
    assert book.metadata_json is None


def test_enrich_skips_already_enriched(session):
    book = _book_with_isbn(session)
    book.work_key = "OL123W"
    session.commit()

    assert enrich_book(session, book) is False


@respx.mock
def test_enrich_no_isbn_noop(session):
    author = Author(name="Anon")
    book = Book(title="No Isbn", author=author)
    session.add(book)
    session.commit()

    assert enrich_book(session, book) is False


@respx.mock
def test_enrich_idempotent_subjects(session):
    respx.get(url__startswith="https://openlibrary.org/api/books").mock(
        return_value=Response(200, json=OL_DETAILS)
    )
    book = _book_with_isbn(session)

    enrich_book(session, book)
    enrich_book(session, book)

    assert len(book.subjects) == 1


@respx.mock
def test_enrich_library_batch(session):
    respx.get(url__startswith="https://openlibrary.org/api/books").mock(
        return_value=Response(
            200, json={**OL_DETAILS, **OL_DETAILS_SECOND_ISBN}
        )
    )
    b1 = _book_with_isbn(session)
    b2 = _book_with_isbn(session, isbn="9780306406157")

    enriched = enrich_library(session)

    assert enriched == 2
    assert b1.work_key == "OL123W"
    assert b2.work_key == "OL999W"
