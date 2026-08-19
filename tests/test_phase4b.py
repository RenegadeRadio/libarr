"""Phase 4 — calibredb export bridge + per-user shelves."""

import subprocess

from libarr.db import session_factory
from libarr.models import Author, Book, Edition, File


def _seed_book_with_file(
    session, *, title="Dune", author="Frank Herbert", path="/data/books/Dune.epub", fmt="EPUB"
):
    a = Author(name=author)
    b = Book(title=title, author=a)
    session.add_all([a, b])
    session.flush()
    e = Edition(book_id=b.id, isbn13=None, format=fmt)
    session.add(e)
    session.flush()
    f = File(edition_id=e.id, path=path, format=fmt, size_bytes=100, sha256="a" * 64)
    session.add(f)
    session.commit()
    return b, f


# --- calibredb export bridge ---------------------------------------------------


def test_export_to_calibre_builds_calibredb_command(client, db, tmp_path, monkeypatch):
    client, db = client
    src = tmp_path / "Dune.epub"
    src.write_bytes(b"epub")
    with session_factory(db)() as session:
        book, file_row = _seed_book_with_file(session, path=str(src))

    seen = {}

    def _fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr("subprocess.run", _fake_run)

    resp = client.post(
        "/api/v1/system/export-calibre",
        json={"library": str(tmp_path / "calibre-lib"), "book_ids": [book.id]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["exported"] == 1
    assert seen["cmd"][0] == "calibredb"
    assert seen["cmd"][1] == "add"
    assert seen["cmd"][3] == str(tmp_path / "calibre-lib")
    assert seen["cmd"][4] == str(src)


def test_export_calibre_missing_binary(client, db, tmp_path, monkeypatch):
    client, db = client
    src = tmp_path / "Dune.epub"
    src.write_bytes(b"epub")
    with session_factory(db)() as session:
        book, file_row = _seed_book_with_file(session, path=str(src))

    def _fail(cmd, **kwargs):
        raise FileNotFoundError("calibredb")

    monkeypatch.setattr("subprocess.run", _fail)

    resp = client.post(
        "/api/v1/system/export-calibre",
        json={"library": str(tmp_path / "calibre-lib"), "book_ids": [book.id]},
    )
    assert resp.status_code == 400
    assert "calibredb" in resp.json()["detail"]


def test_export_calibre_no_file_skips(client, db, tmp_path, monkeypatch):
    client, db = client
    with session_factory(db)() as session:
        book, _ = _seed_book_with_file(
            session, path=str(tmp_path / "missing.epub")
        )  # file doesn't exist on disk

    seen = {"n": 0}

    def _fake_run(cmd, **kwargs):
        seen["n"] += 1
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr("subprocess.run", _fake_run)

    resp = client.post(
        "/api/v1/system/export-calibre",
        json={"library": str(tmp_path / "calibre-lib"), "book_ids": [book.id]},
    )
    assert resp.json()["exported"] == 0
    assert seen["n"] == 0


# --- per-user shelves ------------------------------------------------------------


def test_shelf_lifecycle(client, db):
    client, db = client
    with session_factory(db)() as session:
        b1, _ = _seed_book_with_file(session, title="Dune")
        b2, _ = _seed_book_with_file(
            session,
            title="Neuromancer",
            author="William Gibson",
            path="/data/books/Neuromancer.epub",
        )

    # create
    resp = client.post("/api/v1/shelves", json={"name": "Favorites"})
    assert resp.status_code == 200, resp.text
    shelf_id = resp.json()["id"]

    # add books
    resp = client.post(f"/api/v1/shelves/{shelf_id}/books", json={"book_ids": [b1.id, b2.id]})
    assert resp.status_code == 200
    assert len(resp.json()["book_ids"]) == 2

    # list
    shelves = client.get("/api/v1/shelves").json()
    assert len(shelves) == 1
    assert shelves[0]["name"] == "Favorites"
    assert shelves[0]["book_count"] == 2

    # detail
    detail = client.get(f"/api/v1/shelves/{shelf_id}").json()
    assert {b["title"] for b in detail["books"]} == {"Dune", "Neuromancer"}

    # remove a book
    resp = client.delete(f"/api/v1/shelves/{shelf_id}/books?book_ids={b1.id}")
    assert resp.json()["book_count"] == 1

    # delete shelf
    resp = client.delete(f"/api/v1/shelves/{shelf_id}")
    assert resp.status_code == 200
    assert client.get("/api/v1/shelves").json() == []


def test_shelves_are_per_user(client, db):
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

    resp = client.post("/api/v1/shelves", json={"name": "Mine"})
    assert resp.status_code == 200

    client.post("/api/v1/auth/login", json={"username": "reader", "password": "readerpass"})
    shelves = client.get("/api/v1/shelves").json()
    assert shelves == []  # the other user's shelf is invisible
