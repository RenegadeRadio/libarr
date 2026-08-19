"""Library scan: walk the library root, hash, parse, extract OPF, upsert records.

Design notes (plan §4.3 flow A):
- EPUB metadata (OPF) wins over filename parsing when present.
- ISBN (normalized to ISBN-13) is the join key for editions.
- Re-scans are idempotent: files are matched by path, sha256 detects changes.
- FTS rows are rebuilt for every book touched by a scan.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from libarr.acquisition.epub_meta import read_opf_metadata
from libarr.acquisition.parser import EBOOK_EXTENSIONS, STRONG_EXTENSIONS, parse_book_filename
from libarr.fts import reindex_book
from libarr.metadata.normalize import normalize_isbn, normalize_text
from libarr.models import Author, Book, Edition, File


@dataclass
class ScanResult:
    files_found: int = 0
    files_added: int = 0
    files_updated: int = 0
    errors: int = 0


def scan_library(session: Session, library_root: Path) -> ScanResult:
    """Index every ebook under library_root; returns a summary of what happened."""
    result = ScanResult()
    if not library_root.is_dir():
        return result

    for path in sorted(library_root.rglob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower().lstrip(".")
        # Weak extensions (.txt) are not scan-able books — filename-only identity.
        if ext not in EBOOK_EXTENSIONS or ext not in STRONG_EXTENSIONS:
            continue
        result.files_found += 1
        try:
            added = upsert_file(session, path)
            result.files_added += int(added)
            result.files_updated += int(not added)
        except Exception:  # noqa: BLE001 — one bad file must not abort the scan
            result.errors += 1

    session.commit()
    return result


def upsert_file(session: Session, path: Path) -> bool:
    """Index one ebook file. True when a new File row was created."""
    sha = _sha256(path)
    existing = session.scalars(select(File).where(File.path == str(path))).first()
    if existing is not None:
        existing.sha256 = sha
        existing.size_bytes = path.stat().st_size
        return False

    parsed = parse_book_filename(path.name)
    opf = read_opf_metadata(path) if path.suffix.lower() == ".epub" else None

    title = (opf.get("title") if opf else None) or (parsed.title if parsed else None)
    if not title:
        return False  # unidentifiable file — leave for manual handling

    opf_authors = opf["authors"] if opf else []
    author_name = opf_authors[0] if opf_authors else (parsed.author if parsed else None)
    opf_isbn = opf.get("isbn") if opf else None
    parsed_isbn = parsed.isbn if parsed else None
    isbn = normalize_isbn(opf_isbn or parsed_isbn)
    year = parsed.year if parsed else None
    language = opf.get("language") if opf else None

    author = _upsert_author(session, author_name) if author_name else None
    book = _find_book(session, author.id if author else None, title)
    if book is None:
        book = Book(
            author_id=author.id if author else None,
            title=title,
            year=year,
            language=language,
        )
        session.add(book)
        session.flush()

    fmt = path.suffix.lower().lstrip(".")
    edition = _upsert_edition(session, book, isbn, fmt)
    session.add(
        File(
            edition_id=edition.id,
            path=str(path),
            format=fmt.upper(),
            size_bytes=path.stat().st_size,
            sha256=sha,
        )
    )
    session.flush()
    reindex_book(session, book.id)
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _upsert_author(session: Session, name: str) -> Author:
    norm = normalize_text(name)
    for author in session.scalars(select(Author)):
        if normalize_text(author.name) == norm:
            return author
    author = Author(name=name)
    session.add(author)
    session.flush()
    return author


def _find_book(session: Session, author_id: int | None, title: str) -> Book | None:
    norm = normalize_text(title)
    for book in session.scalars(select(Book).where(Book.author_id == author_id)):
        if normalize_text(book.title) == norm:
            return book
    return None


def _upsert_edition(session: Session, book: Book, isbn: str | None, fmt: str) -> Edition:
    if isbn is not None:
        existing = session.scalars(select(Edition).where(Edition.isbn13 == isbn)).first()
        if existing is not None:
            return existing
    else:
        for edition in book.editions:
            if (edition.format or "").lower() == fmt:
                return edition
    edition = Edition(book_id=book.id, isbn13=isbn, format=fmt.upper())
    session.add(edition)
    session.flush()
    return edition
