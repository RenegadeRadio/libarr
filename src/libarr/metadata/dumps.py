"""Open Library dump ingestion + offline metadata (plan 2.5).

The anti-Readarr resilience core: once `ol_dump_*` files are ingested into
`dump_rows` / `dump_isbns`, every metadata lookup that matters (ISBN →
edition → work → authors → subjects) resolves with zero network access —
the app survives a full Open Library outage.

Dump line format (ol_dump_works.txt etc.): one JSON object per line,
sorted by key. Ingestion is streaming and resumable: the last ingested key
per kind is remembered in the settings table, so re-running against the
monthly refresh only appends what is new.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from libarr.metadata.providers import BookMetadata
from libarr.models import DumpIsbn, DumpRow, Setting

DUMP_KINDS = ("work", "edition", "author")

_ISBN13_RE = re.compile(r"^97[89]\d{10}$")


def parse_dump_line(line: str) -> tuple[str, dict[str, Any]] | None:
    """One dump line → (ol_key, record), or None for blank/delete/malformed."""
    line = line.strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None
    record_type = record.get("type") or {}
    if isinstance(record_type, dict) and record_type.get("key") == "/type/delete":
        return None
    key = record.get("key")
    if not isinstance(key, str) or not key:
        return None
    return key, record


def _iter_dump_lines(path: Path) -> Iterator[str]:
    with open(path, encoding="utf-8", errors="replace") as handle:
        yield from handle


def _last_key(session: Session, kind: str) -> str | None:
    row = session.scalars(select(Setting).where(Setting.key == f"dump_last_key:{kind}")).first()
    return row.value if row is not None else None


def _set_last_key(session: Session, kind: str, key: str) -> None:
    row = session.scalars(select(Setting).where(Setting.key == f"dump_last_key:{kind}")).first()
    if row is not None:
        row.value = key
    else:
        session.add(Setting(key=f"dump_last_key:{kind}", value=key))


def _record_year(record: dict[str, Any]) -> int | None:
    match = re.search(r"(1[89]\d{2}|20\d{2})", str(record.get("publish_date") or ""))
    return int(match.group(1)) if match else None


def _normalize_isbn(value: Any) -> str | None:
    text = re.sub(r"[^0-9Xx]", "", str(value or ""))
    return text if _ISBN13_RE.match(text) else None


def ingest_dump(session: Session, path: Path, *, kind: str) -> int:
    """Stream one dump file into the local mirror; returns rows ingested.

    Resumable: lines whose key sorts at or before the stored last key are
    skipped (dump files are sorted by key). Re-running after appending new
    lines to the file only ingests the additions.
    """
    if kind not in DUMP_KINDS:
        raise ValueError(f"unknown dump kind: {kind}")
    last = _last_key(session, kind)
    ingested = 0
    key = ""
    buffer: list[dict[str, Any]] = []
    isbn_buffer: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal buffer, isbn_buffer
        if buffer:
            session.execute(insert(DumpRow), buffer)
        if isbn_buffer:
            session.execute(
                insert(DumpIsbn).prefix_with("OR IGNORE"),
                isbn_buffer,
            )
        session.commit()
        buffer = []
        isbn_buffer = []

    for line in _iter_dump_lines(path):
        parsed = parse_dump_line(line)
        if parsed is None:
            continue
        key, record = parsed
        if last is not None and key <= last:
            continue
        buffer.append(
            {"ol_key": key, "kind": kind, "payload_json": json.dumps(record, ensure_ascii=False)}
        )
        if kind == "edition":
            works = record.get("works") or []
            work_key = works[0].get("key") if works and isinstance(works[0], dict) else None
            for raw_isbn in record.get("isbn_13") or []:
                isbn13 = _normalize_isbn(raw_isbn)
                if isbn13:
                    isbn_buffer.append(
                        {
                            "isbn13": isbn13,
                            "edition_key": key,
                            "work_key": work_key,
                            "title": str(record.get("title") or ""),
                        }
                    )
        ingested += 1
        if len(buffer) >= 5000:
            flush()
            _set_last_key(session, kind, key)

    flush()
    _set_last_key(session, kind, key if ingested else (last or ""))
    session.commit()
    return ingested


def resolve_isbn_from_dump(session: Session, isbn13: str) -> BookMetadata | None:
    """Full offline ISBN resolution: index → edition → work → author names."""
    index = session.get(DumpIsbn, isbn13)
    if index is None:
        return None
    edition = session.get(DumpRow, index.edition_key)
    if edition is None:
        return None
    edition_record = json.loads(edition.payload_json)

    meta = BookMetadata(
        title=edition_record.get("title") or index.title,
        year=_record_year(edition_record),
        publisher=_record_publisher(edition_record),
        language=_record_language(edition_record),
        isbn13=isbn13,
        edition_key=index.edition_key,
    )

    work_key = index.work_key
    if work_key:
        meta.work_key = work_key.removeprefix("/works/")
        work = session.get(DumpRow, work_key)
        if work is not None:
            work_record = json.loads(work.payload_json)
            meta.subjects = [str(s) for s in (work_record.get("subjects") or [])]
            if meta.year is None:
                first = str(work_record.get("first_publish_date") or "")
                match = re.search(r"(1[89]\d{2}|20\d{2})", first)
                if match:
                    meta.year = int(match.group(1))
            authors: list[str] = []
            for role in work_record.get("authors") or []:
                author_key = None
                if isinstance(role, dict):
                    author = role.get("author")
                    if isinstance(author, dict):
                        author_key = author.get("key")
                    else:
                        author_key = role.get("author")
                if isinstance(author_key, str) and author_key:
                    author_row = session.get(DumpRow, author_key)
                    if author_row is not None:
                        author_record = json.loads(author_row.payload_json)
                        name = author_record.get("name")
                        if isinstance(name, str) and name:
                            authors.append(name)
            if authors:
                meta.authors = authors
    return meta


def _record_publisher(record: dict[str, Any]) -> str | None:
    publishers = record.get("publishers") or []
    return str(publishers[0]) if publishers else None


def _record_language(record: dict[str, Any]) -> str | None:
    languages = record.get("languages") or []
    if languages and isinstance(languages[0], dict):
        key = languages[0].get("key")
        if isinstance(key, str):
            return key.rsplit("/", 1)[-1]
    return None
