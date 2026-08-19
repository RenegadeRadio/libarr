"""Phase 4 — Calibre metadata.db compatibility mode + admin roles + Postgres."""

import sqlite3
from pathlib import Path

from sqlalchemy import select

from libarr.db import make_engine, session_factory
from libarr.models import Book, File


def _make_calibre_library(root: Path) -> None:
    """A minimal but schema-accurate Calibre library (books/authors/data)."""
    db = sqlite3.connect(root / "metadata.db")
    db.executescript(
        """
        CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT NOT NULL, path TEXT);
        CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT NOT NULL, sort TEXT);
        CREATE TABLE books_authors_link (book INTEGER, author INTEGER);
        CREATE TABLE data (id INTEGER PRIMARY KEY, book INTEGER, format TEXT, name TEXT);
        """
    )
    db.executemany(
        "INSERT INTO books (id, title, path) VALUES (?, ?, ?)",
        [(1, "Dune", "Dune (1)"), (2, "Neuromancer", "Neuromancer (2)")],
    )
    db.executemany(
        "INSERT INTO authors (id, name, sort) VALUES (?, ?, ?)",
        [(1, "Frank Herbert", "Herbert, Frank"), (2, "William Gibson", "Gibson, William")],
    )
    db.executemany(
        "INSERT INTO books_authors_link (book, author) VALUES (?, ?)",
        [(1, 1), (2, 2)],
    )
    db.executemany(
        "INSERT INTO data (id, book, format, name) VALUES (?, ?, ?, ?)",
        [
            (1, 1, "EPUB", "Dune - Frank Herbert"),
            (2, 1, "AZW3", "Dune - Frank Herbert"),
            (3, 2, "EPUB", "Neuromancer - William Gibson"),
        ],
    )
    db.commit()
    db.close()

    book1 = root / "Dune (1)"
    book1.mkdir()
    (book1 / "Dune - Frank Herbert.epub").write_bytes(b"epub1")
    (book1 / "Dune - Frank Herbert.azw3").write_bytes(b"azw3")
    book2 = root / "Neuromancer (2)"
    book2.mkdir()
    (book2 / "Neuromancer - William Gibson.epub").write_bytes(b"epub2")


def test_scan_calibre_library_finds_books(tmp_path):
    from libarr.calibre_import import scan_calibre_library

    lib = tmp_path / "calibre"
    lib.mkdir()
    _make_calibre_library(lib)

    entries = scan_calibre_library(lib)
    assert len(entries) == 3
    by_name = {e.title: e for e in entries}
    assert by_name["Dune"].author == "Frank Herbert"
    assert by_name["Dune"].format == "EPUB"
    assert by_name["Dune"].path.is_file()
    assert by_name["Dune"].path.suffix == ".epub"


def test_scan_calibre_missing_db_raises(tmp_path):
    from libarr.calibre_import import CalibreError, scan_calibre_library

    try:
        scan_calibre_library(tmp_path / "empty")
    except CalibreError:
        pass
    else:
        raise AssertionError("expected CalibreError")


def test_import_calibre_library(client, db, tmp_path):
    client, db = client
    lib = tmp_path / "calibre"
    lib.mkdir()
    _make_calibre_library(lib)

    resp = client.post("/api/v1/system/import-calibre", json={"path": str(lib)})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"added": 3, "skipped": 0}  # 3 files: Dune EPUB+AZW3, Neuromancer EPUB

    # re-import is idempotent
    resp = client.post("/api/v1/system/import-calibre", json={"path": str(lib)})
    assert resp.json() == {"added": 0, "skipped": 3}

    with session_factory(db)() as session:
        books = session.scalars(select(Book).order_by(Book.title)).all()
        assert [b.title for b in books] == ["Dune", "Neuromancer"]
        files = session.scalars(select(File)).all()
        assert len(files) == 3
        assert {f.format for f in files} == {"EPUB", "AZW3"}
        assert all(Path(f.path).is_file() for f in files)


# --- Admin roles ---------------------------------------------------------------


def test_users_list_requires_admin(client, db):
    client, db = client
    from libarr.models import User

    with session_factory(db)() as session:
        session.add(
            User(username="reader", password_hash="x" * 40, role="user", api_key="key-reader")
        )
        session.commit()

    resp = client.get("/api/v1/users")
    assert resp.status_code == 200
    usernames = {u["username"] for u in resp.json()}
    assert "admin" in usernames
    assert "reader" in usernames


def test_users_list_forbidden_for_non_admin(client, db):
    client, db = client
    from libarr.api.auth import hash_password
    from libarr.models import User

    with session_factory(db)() as session:
        session.add(
            User(
                username="reader",
                password_hash=hash_password("readerpass"),
                role="user",
                api_key="key-reader",
            )
        )
        session.commit()

    client.post("/api/v1/auth/login", json={"username": "reader", "password": "readerpass"})
    resp = client.get("/api/v1/users")
    assert resp.status_code == 403


def test_admin_can_promote_user(client, db):
    client, db = client
    from libarr.models import User

    with session_factory(db)() as session:
        session.add(
            User(username="reader", password_hash="x" * 40, role="user", api_key="key-reader")
        )
        session.commit()

    resp = client.patch("/api/v1/users/reader", json={"role": "admin"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


def test_non_admin_cannot_promote(client, db):
    client, db = client
    from libarr.api.auth import hash_password
    from libarr.models import User

    with session_factory(db)() as session:
        session.add(
            User(
                username="reader",
                password_hash=hash_password("readerpass"),
                role="user",
                api_key="key-reader",
            )
        )
        session.commit()

    client.post("/api/v1/auth/login", json={"username": "reader", "password": "readerpass"})
    resp = client.patch("/api/v1/users/reader", json={"role": "admin"})
    assert resp.status_code == 403


# --- Postgres backend ----------------------------------------------------------


def test_make_engine_accepts_postgres_url():
    engine = make_engine("postgresql+psycopg://user:pass@dbhost:5432/libarr")
    assert engine.url.get_backend_name() == "postgresql"
    assert engine.url.database == "libarr"
    engine.dispose()
