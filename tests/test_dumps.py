"""Phase 2.5 — OL dump ingestion + offline metadata resolution."""

from pathlib import Path

import respx
from httpx import Response
from sqlalchemy import func, select

from libarr.db import session_factory
from libarr.metadata.dumps import (
    ingest_dump,
    parse_dump_line,
    resolve_isbn_from_dump,
)
from libarr.models import DumpIsbn, DumpRow

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_dump_line_extracts_key_and_record():
    line = '{"key": "/works/OL1W", "type": {"key": "/type/work"}, "title": "Dune"}'
    key, record = parse_dump_line(line)
    assert key == "/works/OL1W"
    assert record["title"] == "Dune"


def test_parse_dump_line_skips_blanks_and_deletes():
    assert parse_dump_line("") is None
    assert parse_dump_line("\n") is None
    deleted = '{"key": "/authors/OL9A", "type": {"key": "/type/delete"}}'
    assert parse_dump_line(deleted) is None


def test_parse_dump_line_tolerates_malformed():
    assert parse_dump_line("not json at all") is None


def test_infer_kind_from_filename():
    from libarr.cli import _infer_kind

    assert _infer_kind(Path("ol_dump_works.txt")) == "work"
    assert _infer_kind(Path("ol_dump_editions.txt")) == "edition"
    assert _infer_kind(Path("ol_dump_authors.txt")) == "author"
    assert _infer_kind(Path("random.txt")) is None


def test_ingest_works_into_dump_rows(client, db):
    client, db = client
    with session_factory(db)() as session:
        count = ingest_dump(session, FIXTURES / "dump_works.txt", kind="work")
        assert count == 2
    with session_factory(db)() as session:
        rows = session.scalars(select(DumpRow).where(DumpRow.kind == "work")).all()
        assert {r.ol_key for r in rows} == {"/works/OL1W", "/works/OL2W"}
        dune = session.get(DumpRow, "/works/OL1W")
        assert '"Science fiction"' in dune.payload_json


def test_ingest_skips_deletes_and_counts(client, db):
    client, db = client
    with session_factory(db)() as session:
        count = ingest_dump(session, FIXTURES / "dump_authors.txt", kind="author")
        assert count == 2  # the /type/delete line is skipped
    with session_factory(db)() as session:
        assert session.get(DumpRow, "/authors/OL999A") is None


def test_ingest_incremental_resumes(client, db):
    """Re-ingesting the same file must not duplicate rows."""
    client, db = client
    with session_factory(db)() as session:
        ingest_dump(session, FIXTURES / "dump_works.txt", kind="work")
        again = ingest_dump(session, FIXTURES / "dump_works.txt", kind="work")
        assert again == 0  # everything already known
    with session_factory(db)() as session:
        assert session.scalar(select(func.count()).select_from(DumpRow)) == 2


def test_ingest_editions_builds_isbn_index(client, db):
    client, db = client
    with session_factory(db)() as session:
        ingest_dump(session, FIXTURES / "dump_editions.txt", kind="edition")
    with session_factory(db)() as session:
        index = session.get(DumpIsbn, "9780441013593")
        assert index is not None
        assert index.edition_key == "/books/OL1M"
        assert index.work_key == "/works/OL1W"
        assert index.title == "Dune"
        assert session.get(DumpIsbn, "9780441569595").work_key == "/works/OL2W"
        # Edition without a work: no index entry beyond the ISBN row.
        assert session.get(DumpIsbn, "9780441172719").work_key is None


def test_resolve_isbn_from_dump_merges_work_and_author(client, db):
    client, db = client
    with session_factory(db)() as session:
        ingest_dump(session, FIXTURES / "dump_editions.txt", kind="edition")
        ingest_dump(session, FIXTURES / "dump_works.txt", kind="work")
        ingest_dump(session, FIXTURES / "dump_authors.txt", kind="author")

        meta = resolve_isbn_from_dump(session, "9780441013593")

    assert meta is not None
    assert meta.title == "Dune"
    assert meta.authors == ["Frank Herbert"]  # resolved through the work's author key
    assert meta.year == 2005  # edition publish date
    assert "Science fiction" in (meta.subjects or [])
    assert meta.isbn13 == "9780441013593"


def test_resolve_isbn_from_dump_unknown_isbn(client, db):
    client, db = client
    with session_factory(db)() as session:
        ingest_dump(session, FIXTURES / "dump_editions.txt", kind="edition")
        ingest_dump(session, FIXTURES / "dump_works.txt", kind="work")
        ingest_dump(session, FIXTURES / "dump_authors.txt", kind="author")
        assert resolve_isbn_from_dump(session, "9780000000000") is None


@respx.mock
def test_provider_falls_back_to_dump_when_offline(client, db):
    """Provider-down drill: OL 500s, but the dump mirror still resolves."""
    client, db = client
    with session_factory(db)() as session:
        ingest_dump(session, FIXTURES / "dump_editions.txt", kind="edition")
        ingest_dump(session, FIXTURES / "dump_works.txt", kind="work")
        ingest_dump(session, FIXTURES / "dump_authors.txt", kind="author")

    respx.get("https://openlibrary.org/api/books").mock(return_value=Response(500))

    from libarr.metadata.providers.openlibrary import OpenLibraryProvider

    with session_factory(db)() as session:
        meta = OpenLibraryProvider(session).lookup_by_isbn("9780441013593")

    assert meta is not None
    assert meta.title == "Dune"
    assert meta.authors == ["Frank Herbert"]
    assert "Science fiction" in (meta.subjects or [])
