"""Shared types for the indexer layer (plan 2.1)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


class IndexerError(Exception):
    """Raised when an indexer fails to serve a query — one dead indexer must
    never block the others (per-indexer failure isolation)."""


@dataclass(slots=True)
class Release:
    """A single search result from any indexer, normalized."""

    title: str
    indexer_name: str
    download_url: str
    guid: str
    author: str | None = None
    year: int | None = None
    isbn: str | None = None
    format: str | None = None
    size_bytes: int | None = None
    seeders: int | None = None
    peers: int | None = None
    published_at: datetime | None = None
    page_url: str | None = None  # human-readable page (Gutenberg/SE)
    subjects: list[str] = field(default_factory=list)


_FORMAT_PATTERNS: list[tuple[str, str]] = [
    ("EPUB", r"\.epub\b|\bepub\b"),
    ("AZW3", r"\.azw3\b|\bazw3\b"),
    ("MOBI", r"\.mobi\b|\bmobi\b"),
    ("PDF", r"\.pdf\b|\bpdf\b"),
    ("FB2", r"\.fb2\b|\bfb2\b"),
    ("M4B", r"\.m4b\b|\bm4b\b|\baudible\b"),
    ("MP3", r"\.mp3\b|\bmp3\b"),
]

# Audio check must run before text formats share tokens (e.g. "MP3").
_FORMAT_ORDER = ["EPUB", "AZW3", "MOBI", "PDF", "FB2", "M4B", "MP3"]


def detect_format(title: str) -> str | None:
    """Detect the ebook format from a release title (best-effort)."""
    lowered = title.lower()
    for fmt in _FORMAT_ORDER:
        pattern = dict(_FORMAT_PATTERNS)[fmt]
        if re.search(pattern, lowered):
            return fmt
    return None


def as_int(value: str | int | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class IndexerClient(Protocol):
    """The common surface every indexer adapter implements."""

    name: str

    def search(self, q: str) -> list[Release]: ...

    def recent(self, limit: int = 100) -> list[Release]: ...


def year_from_title(title: str) -> int | None:
    match = re.search(r"(1[89]\d\d|20\d\d)", title)
    return int(match.group(1)) if match else None
