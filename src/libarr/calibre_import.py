"""Calibre `metadata.db` compatibility mode (Phase 4).

Reads a Calibre library directory read-only (books, authors, formats, file
paths) and imports its files into the Libarr library. Write-through and
`calibredb` bridging are intentionally out of scope — Libarr never modifies
a Calibre library; it ingests from it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from libarr.fts import reindex_book
from libarr.metadata.normalize import normalize_text
from libarr.models import Author, Book, Edition, File


class CalibreError(Exception):
    """Raised when the path is not a readable Calibre library."""


@dataclass(slots=True)
class CalibreEntry:
    title: str
    author: str
    format: str
    path: Path


def scan_calibre_library(library_path: Path) -> list[CalibreEntry]:
    """Read every format file in the library's metadata.db (read-only)."""
    db_path = Path(library_path) / "metadata.db"
    if not db_path.is_file():
        raise CalibreError(f"no metadata.db found at {library_path}")

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            SELECT b.title, a.name, d.format, b.path, d.name
            FROM books b
            JOIN books_authors_link bal ON bal.book = b.id
            JOIN authors a ON a.id = bal.author
            JOIN data d ON d.book = b.id
            """
        ).fetchall()
    finally:
        conn.close()

    entries: list[CalibreEntry] = []
    seen: set[Path] = set()
    for title, author, fmt, book_path, file_name in rows:
        file_path = Path(library_path) / (book_path or "") / f"{file_name}.{fmt.lower()}"
        if not file_path.is_file() or file_path in seen:
            continue
        seen.add(file_path)
        entries.append(
            CalibreEntry(title=title, author=author or "", format=fmt.upper(), path=file_path)
        )
    return entries


def _existing_paths(session: Session) -> set[str]:
    return {p for (p,) in session.execute(select(File.path)).all()}


def import_calibre_library(session: Session, library_path: Path) -> dict[str, int]:
    """Import a Calibre library into Libarr; idempotent per file path."""
    entries = scan_calibre_library(library_path)
    existing = _existing_paths(session)
    added = 0
    skipped = 0
    for entry in entries:
        if str(entry.path) in existing:
            skipped += 1
            continue

        author = session.scalars(select(Author).where(Author.name == entry.author)).first()
        if author is None:
            author = Author(name=entry.author or "Unknown")
            session.add(author)
            session.flush()

        book = None
        for candidate in session.scalars(select(Book)).all():
            if (
                normalize_text(candidate.title) == normalize_text(entry.title)
                and candidate.author is not None
                and normalize_text(candidate.author.name) == normalize_text(entry.author)
            ):
                book = candidate
                break
        if book is None:
            book = Book(title=entry.title, author=author)
            session.add(book)
            session.flush()
            reindex_book(session, book.id)

        edition = session.scalars(select(Edition).where(Edition.book_id == book.id)).first()
        if edition is None:
            edition = Edition(book_id=book.id, isbn13=None, format=entry.format)
            session.add(edition)
            session.flush()

        session.add(
            File(
                edition_id=edition.id,
                path=str(entry.path),
                format=entry.format,
                size_bytes=entry.path.stat().st_size,
                sha256="calibre-import",  # placeholder: real hash is lazy/optional
            )
        )
        existing.add(str(entry.path))
        added += 1
    session.commit()
    return {"added": added, "skipped": skipped}


def export_to_calibre(
    session: Session,
    library_path: Path,
    book_ids: list[int],
    *,
    command: str = "calibredb",
) -> dict[str, int]:
    """Push Libarr books into a Calibre library via the `calibredb` CLI.

    The bridge shells out to Calibre's own tool (GPL-clean — no Calibre code
    embedded); the Calibre library is always the authority, we only add.
    """
    import subprocess

    exported = 0
    for book in session.scalars(select(Book).where(Book.id.in_(book_ids))).all():
        file_path = _best_file_path(session, book)
        if file_path is None or not Path(file_path).is_file():
            continue
        try:
            subprocess.run(
                [command, "add", "--with-library", str(library_path), file_path],
                capture_output=True,
                text=True,
                timeout=300,
                check=True,
            )
        except FileNotFoundError as exc:
            raise CalibreError(
                f"calibredb not found on PATH ({command}) — install Calibre or point at the binary"
            ) from exc
        exported += 1
    return {"exported": exported}


def _best_file_path(session: Session, book: Book) -> str | None:
    from libarr.acquisition.wanted import best_imported_format

    best = best_imported_format(session, book)
    if best is None:
        return None
    for edition in book.editions:
        for file_row in edition.files:
            if file_row.format == best:
                return file_row.path
    return None
