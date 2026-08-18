"""Phase 1.2 — library scan: walk, hash, OPF extraction, upsert, dedupe."""

import hashlib

from sqlalchemy import select, text

from libarr.acquisition.library_scan import ScanResult, scan_library
from libarr.models import Author, Book, File
from tests.fixtures.make_epub import make_epub


def _sha256_of(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_scan_indexes_books(tmp_path, session):
    lib = tmp_path / "library"
    lib.mkdir()
    stand = make_epub(
        lib / "The Stand - Stephen King (1990).epub", "The Stand", "Stephen King",
        isbn="9780451169518",
    )
    make_epub(
        lib / "Dune - Frank Herbert (1965).epub", "Dune", "Frank Herbert",
        isbn="9780441172719",
    )
    (lib / "Neuromancer (1984) - William Gibson.pdf").write_bytes(b"%PDF-1.4 fake")

    result = scan_library(session, lib)

    assert result.files_found == 3
    assert result.files_added == 3
    assert result.errors == 0

    books = session.scalars(select(Book)).all()
    assert {b.title for b in books} == {"The Stand", "Dune", "Neuromancer"}

    king = session.scalars(select(Author).where(Author.name == "Stephen King")).one()
    stand_book = session.scalars(select(Book).where(Book.title == "The Stand")).one()
    assert stand_book.author_id == king.id
    assert stand_book.year == 1990

    edition = stand_book.editions[0]
    assert edition.isbn13 == "9780451169518"
    file_row = edition.files[0]
    assert file_row.sha256 == _sha256_of(stand)
    assert file_row.size_bytes == stand.stat().st_size

    # FTS index was populated for the scan.
    rows = session.execute(
        text("SELECT rowid FROM book_fts WHERE book_fts MATCH :q"), {"q": "herbert"}
    ).all()
    dune = session.scalars(select(Book).where(Book.title == "Dune")).one()
    assert [r[0] for r in rows] == [dune.id]


def test_rescan_dedupes(tmp_path, session):
    lib = tmp_path / "library"
    lib.mkdir()
    make_epub(lib / "Dune - Frank Herbert.epub", "Dune", "Frank Herbert")

    first = scan_library(session, lib)
    second = scan_library(session, lib)

    assert (first.files_found, first.files_added) == (1, 1)
    assert (second.files_found, second.files_added) == (1, 0)
    assert len(session.scalars(select(File)).all()) == 1
    assert len(session.scalars(select(Book)).all()) == 1


def test_opf_metadata_preferred_over_filename(tmp_path, session):
    lib = tmp_path / "library"
    lib.mkdir()
    make_epub(lib / "Wrong Filename.epub", "Real Title", "Real Author")

    scan_library(session, lib)

    book = session.scalars(select(Book)).one()
    assert book.title == "Real Title"
    assert book.author.name == "Real Author"


def test_junk_files_ignored(tmp_path, session):
    lib = tmp_path / "library"
    lib.mkdir()
    (lib / "cover.jpg").write_bytes(b"not a book")
    (lib / "notes.txt").write_bytes(b"not a book either")

    result = scan_library(session, lib)

    assert result.files_found == 0
    assert len(session.scalars(select(File)).all()) == 0


def test_scan_result_counts(tmp_path):
    result = ScanResult()
    assert (result.files_found, result.files_added, result.files_updated, result.errors) == (
        0, 0, 0, 0,
    )
