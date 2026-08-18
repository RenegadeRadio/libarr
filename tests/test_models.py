"""Phase 1.1 — media models: author/book/series/edition/file/subject + FTS5 index."""


import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from libarr.fts import reindex_book
from libarr.models import Author, Book, Edition, File, Series, Subject


def test_author_book_edition_file_chain(session):
    author = Author(name="Stephen King", sort_name="King, Stephen")
    session.add(author)
    session.flush()

    book = Book(
        author_id=author.id,
        title="The Stand",
        year=1990,
        language="eng",
        monitored=True,
    )
    session.add(book)
    session.flush()

    edition = Edition(
        book_id=book.id, isbn13="9780385171683", publisher="Doubleday", format="EPUB"
    )
    session.add(edition)
    session.flush()

    session.add(
        File(
            edition_id=edition.id,
            path="/data/books/The Stand.epub",
            format="EPUB",
            size_bytes=1024,
            sha256="abc123",
        )
    )
    session.commit()

    assert book.author.name == "Stephen King"
    assert book.editions[0].isbn13 == "9780385171683"
    assert book.editions[0].files[0].path.endswith("The Stand.epub")


def test_isbn13_unique(session):
    book = Book(title="A", author_id=None)
    session.add(book)
    session.flush()
    session.add_all(
        [
            Edition(book_id=book.id, isbn13="9780385171683"),
            Edition(book_id=book.id, isbn13="9780385171683"),
        ]
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_file_path_unique(session):
    session.add(File(path="/x.epub", format="EPUB", size_bytes=1, sha256="a"))
    session.flush()
    session.add(File(path="/x.epub", format="EPUB", size_bytes=2, sha256="b"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_subject_upsert_unique(session):
    book = Book(title="B", author_id=None)
    session.add(book)
    session.flush()
    session.add_all(
        [
            Subject(
                book_id=book.id, name="Science Fiction", slug="science-fiction",
                source="openlibrary",
            ),
            Subject(
                book_id=book.id, name="Science Fiction", slug="science-fiction",
                source="user",
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_series_relationship(session):
    author = Author(name="Brandon Sanderson")
    session.add(author)
    session.flush()
    series = Series(title="Mistborn", author_id=author.id, sort_order=1)
    session.add(series)
    session.flush()
    book = Book(
        author_id=author.id, title="The Final Empire",
        series_id=series.id, series_position=1,
    )
    session.add(book)
    session.commit()
    assert book.series.title == "Mistborn"


def test_book_fts_reindex_and_search(session):
    author = Author(name="Frank Herbert")
    book = Book(
        author_id=None, title="Dune", description="Desert planet politics.", year=1965
    )
    book.author = author
    session.add(book)
    session.flush()
    session.add_all(
        [
            Subject(
                book_id=book.id, name="Science Fiction", slug="science-fiction",
                source="openlibrary",
            ),
            Subject(
                book_id=book.id, name="Ecology", slug="ecology", source="openlibrary",
            ),
        ]
    )
    session.commit()

    reindex_book(session, book.id)

    rows = session.execute(
        text("SELECT rowid FROM book_fts WHERE book_fts MATCH :q"), {"q": "dune"}
    ).all()
    assert [r[0] for r in rows] == [book.id]

    rows = session.execute(
        text("SELECT rowid FROM book_fts WHERE book_fts MATCH :q"),
        {"q": "herbert ecology"},
    ).all()
    assert [r[0] for r in rows] == [book.id]
