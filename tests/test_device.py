"""Phase 3 — device delivery: KEPUB pass, Send-to-Kindle, KOReader sync."""

import smtplib
import subprocess
from pathlib import Path

from sqlalchemy import select

from libarr.db import session_factory
from libarr.models import ConversionJob, File


def _seed_book_with_file(session, *, path="/data/books/Dune.epub", fmt="EPUB"):
    from libarr.models import Author, Book, Edition

    a = Author(name="Frank Herbert")
    b = Book(title="Dune", author=a)
    session.add_all([a, b])
    session.flush()
    e = Edition(book_id=b.id, isbn13=None, format=fmt)
    session.add(e)
    session.flush()
    f = File(edition_id=e.id, path=path, format=fmt, size_bytes=1000, sha256="a" * 64)
    session.add(f)
    session.commit()
    return b, f


# --- KEPUB pass (kepubify subprocess) ----------------------------------------


def test_kepub_conversion_uses_kepubify(client, db, tmp_path, monkeypatch):
    from libarr.conversion import enqueue_conversion, process_conversions

    client, db = client
    out_dir = tmp_path / "kobo"
    out_dir.mkdir()
    src = tmp_path / "Dune.epub"
    src.write_bytes(b"fake epub")
    with session_factory(db)() as session:
        book, file_row = _seed_book_with_file(session, path=str(src))
        job = enqueue_conversion(session, file_row, "KEPUB")

    seen = {}

    def _kepubify(cmd, **kwargs):
        seen["cmd"] = cmd
        # kepubify writes <stem>_converted.kepub.epub into --output-dir
        (Path(cmd[2]) / "Dune_converted.kepub.epub").write_bytes(b"k")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr("subprocess.run", _kepubify)

    with session_factory(db)() as session:
        stats = process_conversions(session, out_dir=str(out_dir))

    assert stats["completed"] == 1
    assert seen["cmd"][0] == "kepubify"
    with session_factory(db)() as session:
        job = session.get(ConversionJob, job.id)
        assert job.status == "done"
        assert job.output_path.endswith("_converted.kepub.epub")


# --- Send-to-Kindle -----------------------------------------------------------


def test_send_to_kindle_sends_attachment(client, db, tmp_path, monkeypatch):
    client, db = client
    src = tmp_path / "Dune.azw3"
    src.write_bytes(b"fake azw3")
    with session_factory(db)() as session:
        book, file_row = _seed_book_with_file(session, path=str(src), fmt="AZW3")

    monkeypatch.setenv("LIBARR_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("LIBARR_SMTP_USERNAME", "me@example.com")
    monkeypatch.setenv("LIBARR_SMTP_PASSWORD", "secret")
    monkeypatch.setenv("LIBARR_SMTP_FROM", "me@example.com")

    sent = {}

    class _FakeSMTP:
        def __init__(self, host, port):
            sent["host"] = host
            sent["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, user, password):
            sent["login"] = (user, password)

        def sendmail(self, from_addr, to_addrs, message):
            sent["from"] = from_addr
            sent["to"] = to_addrs
            sent["message"] = message

        def quit(self):
            sent["quit"] = True

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    resp = client.post(f"/api/v1/books/{book.id}/send-to-kindle", json={"to": "kindle@kindle.com"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sent"] is True
    assert body["to"] == "kindle@kindle.com"
    assert sent["to"] == ["kindle@kindle.com"]
    assert "Dune.azw3" in sent["message"]
    assert "application/octet-stream" in sent["message"]


def test_send_to_kindle_requires_smtp_config(client, db, tmp_path, monkeypatch):
    client, db = client
    monkeypatch.delenv("LIBARR_SMTP_HOST", raising=False)
    with session_factory(db)() as session:
        book, file_row = _seed_book_with_file(session, path=str(tmp_path / "Dune.epub"))

    resp = client.post(f"/api/v1/books/{book.id}/send-to-kindle", json={"to": "kindle@kindle.com"})
    assert resp.status_code == 400
    assert "SMTP" in resp.json()["detail"]


def test_send_to_kindle_no_file(client, db):
    client, db = client
    with session_factory(db)() as session:
        from libarr.models import Author, Book

        a = Author(name="Frank Herbert")
        b = Book(title="Dune", author=a)
        session.add_all([a, b])
        session.commit()
        book_id = b.id

    resp = client.post(f"/api/v1/books/{book_id}/send-to-kindle", json={"to": "kindle@kindle.com"})
    assert resp.status_code == 400


# --- KOReader progress sync (koreader-sync-server protocol subset) ------------


def test_koreader_auth_returns_token(client, db):
    client, db = client
    resp = client.post(
        "/koreader/users/auth",
        json={"user": "admin", "password": "hunter2!", "device_id": "dev1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["token"]  # the user's API key doubles as the sync token


def test_koreader_auth_rejects_bad_password(client, db):
    client, db = client
    resp = client.post(
        "/koreader/users/auth",
        json={"user": "admin", "password": "wrong", "device_id": "dev1"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_koreader_progress_upload_and_get(client, db):
    client, db = client
    token = _sync_token(db)

    upload = client.post(
        "/koreader/progress/upload",
        json={
            "token": token,
            "progress": {
                "client": "android",
                "title": "Dune",
                "document": "dune.md5",
                "progress": 0.42,
                "device": "Kobo",
                "time": 1700000000,
            },
        },
    )
    assert upload.status_code == 200
    assert upload.json()["ok"] is True

    fetch = client.post(
        "/koreader/progress/get",
        json={"token": token, "documents": ["dune.md5", "other.md5"]},
    )
    body = fetch.json()
    assert body["ok"] is True
    results = {r["document"]: r for r in body["results"]}
    assert results["dune.md5"]["progress"] == 0.42
    assert "other.md5" not in results


def test_koreader_progress_rejects_bad_token(client, db):
    client, db = client
    upload = client.post(
        "/koreader/progress/upload",
        json={
            "token": "bogus",
            "progress": {
                "client": "android",
                "title": "Dune",
                "document": "x",
                "progress": 0.1,
                "device": "Kobo",
                "time": 1,
            },
        },
    )
    assert upload.json()["ok"] is False


def _sync_token(db):
    """The admin user's API key doubles as the KOReader sync token."""
    from libarr.models import User

    with session_factory(db)() as session:
        return session.scalars(select(User).where(User.username == "admin")).one().api_key
