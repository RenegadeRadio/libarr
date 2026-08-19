"""Phase 1.5 — matcher: ISBN-exact → normalized title/author → FTS fallback."""

from libarr.fts import reindex_book
from libarr.metadata.matcher import match_book
from libarr.models import Author, Book, Edition, Subject


def _add_book(session, title, author=None, isbn=None, subjects=()):
    author_row = Author(name=author) if author else None
    book = Book(title=title, author=author_row)
    session.add(book)
    session.flush()
    if isbn:
        session.add(Edition(book_id=book.id, isbn13=isbn))
    for subj in subjects:
        session.add(
            Subject(book_id=book.id, name=subj, slug=subj.lower().replace(" ", "-"), source="user")
        )
    session.flush()
    reindex_book(session, book.id)
    return book


def test_match_by_isbn_exact(session):
    _add_book(session, "The Stand", "Stephen King", isbn="9780451169518")
    dune = _add_book(session, "Dune", "Frank Herbert", isbn="9780441172719")

    assert match_book(session, title="", isbn="9780441172719").id == dune.id
    # ISBN-10 form of the same edition also matches.
    assert match_book(session, title="", isbn="0-441-17271-7").id == dune.id


def test_match_by_normalized_title_and_author(session):
    _add_book(session, "The Stand", "Stephen King")

    found = match_book(session, title="the stand (unabridged)!", author="STEPHEN KING")
    assert found is not None
    assert found.title == "The Stand"


def test_same_title_different_author_no_match(session):
    _add_book(session, "The Stand", "Stephen King")

    assert match_book(session, title="The Stand", author="Robert McCammon") is None


def test_fts_fallback_matches_fuzzy_title(session):
    _add_book(session, "The Stand", "Stephen King")

    found = match_book(session, title="The Stand Unabridged")
    assert found is not None
    assert found.title == "The Stand"


def test_fts_fallback_rejects_weak_overlap(session):
    _add_book(session, "The Stand", "Stephen King")
    _add_book(session, "The Road", "Cormac McCarthy")

    # Shared token is only "the" — not a match.
    assert match_book(session, title="The Road Trip") is None


def test_fts_fallback_respects_author(session):
    _add_book(session, "Neuromancer", "William Gibson")

    assert match_book(session, title="Neuromancer", author="Stephen King") is None
    found = match_book(session, title="Neuromancer", author="William Gibson")
    assert found is not None and found.title == "Neuromancer"


def test_no_match_for_garbage(session):
    _add_book(session, "Dune", "Frank Herbert")

    assert match_book(session, title="zzzzqqqqx") is None
