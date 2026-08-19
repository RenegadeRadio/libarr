"""Phase 3 — conversion worker (ebook-convert subprocess queue)."""

import subprocess
from pathlib import Path

from sqlalchemy import select

from libarr.conversion import enqueue_conversion, process_conversions
from libarr.db import session_factory
from libarr.models import ConversionJob


def _seed_file(session, path: str = "/data/books/Dune.epub"):
    from libarr.models import Author, Book, Edition, File

    a = Author(name="Frank Herbert")
    b = Book(title="Dune", author=a)
    session.add_all([a, b])
    session.flush()
    e = Edition(book_id=b.id, isbn13=None, format="EPUB")
    session.add(e)
    session.flush()
    f = File(edition_id=e.id, path=path, format="EPUB", size_bytes=1000, sha256="a" * 64)
    session.add(f)
    session.commit()
    return f, b


def test_enqueue_creates_queued_job(client, db):
    client, db = client
    with session_factory(db)() as session:
        file_row, _ = _seed_file(session)
        job = enqueue_conversion(session, file_row, "AZW3")

    assert job.status == "queued"
    assert job.target_format == "AZW3"
    with session_factory(db)() as session:
        rows = session.scalars(select(ConversionJob)).all()
        assert len(rows) == 1


def test_process_conversions_completes(client, db, tmp_path, monkeypatch):
    client, db = client
    out_dir = tmp_path / "converted"
    out_dir.mkdir()
    with session_factory(db)() as session:
        file_row, book = _seed_file(session, path=str(tmp_path / "Dune.epub"))
        (tmp_path / "Dune.epub").write_bytes(b"fake epub")
        job = enqueue_conversion(session, file_row, "AZW3")

    def _fake_run(cmd, **kwargs):
        assert cmd[0] == "ebook-convert"
        assert cmd[1].endswith("Dune.epub")
        Path(cmd[2]).write_bytes(b"converted")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr("subprocess.run", _fake_run)

    with session_factory(db)() as session:
        stats = process_conversions(session, out_dir=str(out_dir))

    assert stats["completed"] == 1
    with session_factory(db)() as session:
        job = session.get(ConversionJob, job.id)
        assert job.status == "done"
        assert job.output_path.endswith(".azw3")
        assert Path(job.output_path).exists()


def test_process_conversions_failure(client, db, tmp_path, monkeypatch):
    client, db = client
    out_dir = tmp_path / "converted"
    out_dir.mkdir()
    with session_factory(db)() as session:
        file_row, book = _seed_file(session, path=str(tmp_path / "Dune.epub"))
        (tmp_path / "Dune.epub").write_bytes(b"fake epub")
        job = enqueue_conversion(session, file_row, "PDF")

    def _fail(cmd, **kwargs):
        raise RuntimeError("ebook-convert exploded")

    monkeypatch.setattr("subprocess.run", _fail)

    with session_factory(db)() as session:
        stats = process_conversions(session, out_dir=str(out_dir))

    assert stats["failed"] == 1
    with session_factory(db)() as session:
        job = session.get(ConversionJob, job.id)
        assert job.status == "failed"
        assert "exploded" in (job.error or "")


def test_process_conversions_skips_nonzero_but_missing_output(client, db, tmp_path, monkeypatch):
    """ebook-convert returned 0 but produced nothing → still a failure."""
    client, db = client
    out_dir = tmp_path / "converted"
    out_dir.mkdir()
    with session_factory(db)() as session:
        file_row, book = _seed_file(session, path=str(tmp_path / "Dune.epub"))
        (tmp_path / "Dune.epub").write_bytes(b"fake epub")
        job = enqueue_conversion(session, file_row, "MOBI")

    def _silent_success(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=0)  # but writes nothing

    monkeypatch.setattr("subprocess.run", _silent_success)

    with session_factory(db)() as session:
        stats = process_conversions(session, out_dir=str(out_dir))

    assert stats["failed"] == 1
    with session_factory(db)() as session:
        assert session.get(ConversionJob, job.id).status == "failed"
