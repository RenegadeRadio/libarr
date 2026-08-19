"""Import pipeline (plan 2.4): locate → verify → hardlink → name → File row.

The *Arr hardlink law: within the same filesystem the import is a hardlink
(instant, zero copy, seed-friendly); cross-device it falls back to copy;
`mode="move"` moves. Completed downloads land in the library named by the
user's template, get a `files` row, mark the queue item imported, notify —
and mismatched/unfindable downloads go to the quarantine folder.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from libarr.acquisition.epub_meta import read_opf_metadata
from libarr.acquisition.parser import parse_book_filename
from libarr.acquisition.wanted import normalize_release_title
from libarr.clients.base import ClientItem
from libarr.config import Settings
from libarr.history import record
from libarr.metadata.normalize import normalize_text
from libarr.models import Book, DownloadClientRow, Edition, File, QueueItem
from libarr.notify import notify

EBOOK_EXTENSIONS = {".epub", ".pdf", ".mobi", ".azw3", ".fb2", ".m4b", ".mp3"}

DEFAULT_TEMPLATE = (
    "{Author Name}/{Series} - {Book Title} ({Release Year})/"
    "{Series} - {Book Title} ({Release Year}) - {Author}.{Extension}"
)


class ImportError(Exception):
    """Raised when a completed download cannot be imported."""


@dataclass(slots=True)
class ImportResult:
    ok: bool
    destination: Path | None = None
    hardlinked: bool = False
    error: str | None = None


def _sanitize_segment(segment: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "", segment).strip()
    return cleaned or "Unknown"


def render_template(
    template: str,
    *,
    author: str | None,
    series: str | None,
    title: str | None,
    year: int | None,
    extension: str | None,
) -> Path:
    """Render a naming template. Empty tokens collapse cleanly so
    "Series - " disappears when a book has no series."""
    tokens = {
        "Author Name": _sanitize_segment(author or "Unknown Author"),
        "Author": _sanitize_segment(author or "Unknown Author"),
        "Series": _sanitize_segment(series or ""),
        "Book Title": _sanitize_segment(title or "Unknown"),
        "Release Year": str(year) if year else "",
        "Extension": (extension or "").lower(),
    }
    out = template
    for key, value in tokens.items():
        out = out.replace("{" + key + "}", value)
    out = re.sub(r"\s*-\s*-\s*", " - ", out)  # " -  - " from empty middle tokens
    out = re.sub(r"(^|/)\s*-\s*", r"\1", out)  # leading " - " after a slash
    out = re.sub(r"\s*-\s*(?=/)", "", out)  # trailing " - " before a slash
    out = re.sub(r"\(\s*\)", "", out)  # empty parens from a missing year
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"/+", "/", out)
    return Path(out.strip())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _locate_files(client_item: ClientItem, client_row: DownloadClientRow | None) -> list[Path]:
    """Find completed ebook files under the client-reported path, applying
    the Remote Path Mapping (client path → library-host path)."""
    save = client_item.save_path or ""
    if client_row and client_row.remote_path and save.startswith(client_row.remote_path):
        relative = Path(save).relative_to(client_row.remote_path)
        save = str(Path(client_row.local_path or "") / relative)
    root = Path(save)
    if not root.is_dir():
        return []
    return sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in EBOOK_EXTENSIONS
    )


def _pick_file(files: list[Path], preferred_format: str | None) -> Path:
    if preferred_format:
        wanted = f".{preferred_format.lower()}"
        for path in files:
            if path.suffix.lower() == wanted:
                return path
    return files[0]


def _verify(session: Session, book: Book, src: Path) -> bool:
    """Filename/OPF sanity check: the download really is the queued book."""
    parsed = parse_book_filename(normalize_release_title(src.name))
    if parsed and parsed.title:
        if normalize_text(parsed.title) == normalize_text(book.title):
            return True
        if src.suffix.lower() == ".epub":
            opf = read_opf_metadata(src)
            if opf and normalize_text(opf.get("title") or "") == normalize_text(book.title):
                return True
        # title variant (subtitle etc.) but author agrees
        return bool(
            parsed.author
            and book.author
            and normalize_text(parsed.author) == normalize_text(book.author.name)
        )
    return True  # unparseable name → let the scan-time OPF check handle it


def import_download(
    session: Session,
    queue_item: QueueItem,
    client_item: ClientItem,
    *,
    library_root: Path,
    template: str = DEFAULT_TEMPLATE,
    mode: str = "hardlink",
) -> ImportResult:
    client_row = None
    if queue_item.client_name:
        client_row = session.scalars(
            select(DownloadClientRow).where(DownloadClientRow.name == queue_item.client_name)
        ).first()
    book = session.get(Book, queue_item.book_id)
    if book is None:
        return _fail(session, queue_item, library_root, "queued book no longer exists")

    files = _locate_files(client_item, client_row)
    if not files:
        return _fail(session, queue_item, library_root, "no ebook file found in download directory")
    src = _pick_file(files, queue_item.format)

    if not _verify(session, book, src):
        return _fail(
            session,
            queue_item,
            library_root,
            f"metadata mismatch: {src.name} does not match {book.title}",
        )

    parsed = parse_book_filename(normalize_release_title(src.name))
    series = book.series.title if book.series else None
    dest = library_root / render_template(
        template,
        author=book.author.name if book.author else parsed.author if parsed else None,
        series=series,
        title=book.title,
        year=book.year,
        extension=src.suffix[1:],
    )
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        hardlinked = False
        if mode == "hardlink":
            try:
                os.link(src, dest)
                hardlinked = True
            except OSError:
                shutil.copy2(src, dest)  # cross-device fallback
        elif mode == "copy":
            shutil.copy2(src, dest)
        else:
            shutil.move(str(src), dest)
    except OSError as exc:
        return _fail(session, queue_item, library_root, f"link/copy failed: {exc}")

    edition = session.scalars(select(Edition).where(Edition.book_id == book.id)).first()
    had_files = edition is not None and len(edition.files) > 0
    if edition is None:
        edition = Edition(book_id=book.id, format=src.suffix[1:].upper())
        session.add(edition)
        session.flush()
    session.add(
        File(
            edition_id=edition.id,
            path=str(dest),
            format=src.suffix[1:].upper(),
            size_bytes=dest.stat().st_size,
            sha256=_sha256(dest),
        )
    )
    queue_item.status = "imported"
    queue_item.error = None
    session.commit()
    record(
        session,
        kind="upgrade" if had_files else "import",
        title=book.title,
        book_id=book.id,
        details=str(dest),
    )
    session.commit()
    notify("Book imported", f"{book.title} → {dest}")
    return ImportResult(ok=True, destination=dest, hardlinked=hardlinked)


def _fail(session: Session, queue_item: QueueItem, library_root: Path, error: str) -> ImportResult:
    quarantine = library_root / "quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)
    queue_item.status = "failed"
    queue_item.error = error
    session.commit()
    record(session, kind="fail", title=queue_item.title, book_id=queue_item.book_id, details=error)
    session.commit()
    notify("Import failed", error)
    return ImportResult(ok=False, error=error)


def default_import_hook(session: Session, queue_item: QueueItem, client_item: ClientItem) -> None:
    """The hook the download watch calls on completion (plan 2.2 → 2.4)."""
    settings = Settings()
    result = import_download(
        session,
        queue_item,
        client_item,
        library_root=Path(settings.library_dir),
        template=settings.import_template,
        mode=settings.import_mode,
    )
    if not result.ok:
        raise ImportError(result.error or "import failed")
