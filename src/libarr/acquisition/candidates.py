"""Release candidate normalization + junk filtering (plan 2.3.3)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from libarr.acquisition.parser import ParsedName, parse_book_filename
from libarr.acquisition.wanted import normalize_release_title
from libarr.indexers.base import Release, detect_format

_JUNK_PATTERNS = [
    re.compile(r"\[sample[^\]]*\]", re.IGNORECASE),
    re.compile(r"\bsample\b", re.IGNORECASE),
    re.compile(r"\bpassword[-\s]?protected\b|\bpassword\b", re.IGNORECASE),
    re.compile(r"\.txt\s*$", re.IGNORECASE),
    re.compile(r"\[unknown\]", re.IGNORECASE),
    re.compile(r"\bscan(?:ned)?\b", re.IGNORECASE),
]

# "Book Club Notes - June 2026.pdf" is a document, not a book: titles whose
# parsed form is a single short token with a weak format are rejected later —
# here we catch the obvious txt/password/sample junk only.


def is_junk(title: str) -> bool:
    """True for obvious junk releases (samples, .txt scans, password-protected)."""
    return any(pattern.search(title) for pattern in _JUNK_PATTERNS)


_PROTOCOL_DIRECT = "direct"
_PROTOCOL_TORRENT = "torrent"
_PROTOCOL_USENET = "usenet"


@dataclass(slots=True)
class Candidate:
    release: Release
    parsed: ParsedName | None
    fmt: str | None
    custom_score: int
    protocol: str
    indexer_priority: int
    seeders: int | None
    age_hours: float | None
    size_bytes: int | None


def detect_protocol(release: Release) -> str:
    url = (release.download_url or "").lower()
    if url.endswith(".nzb") or "nzb" in url:
        return _PROTOCOL_USENET
    if url.startswith("magnet:") or url.endswith(".torrent"):
        return _PROTOCOL_TORRENT
    return _PROTOCOL_DIRECT


def normalize_candidate(
    release: Release,
    *,
    indexer_priority: int = 100,
    protocol: str | None = None,
) -> Candidate | None:
    """Parse + filter a release into a decision-ready candidate, or None."""
    if is_junk(release.title):
        return None
    parsed = parse_book_filename(normalize_release_title(release.title))
    fmt = release.format or detect_format(release.title)
    age_hours = None
    if release.published_at is not None:
        now = datetime.now(release.published_at.tzinfo)
        age_hours = max(0.0, (now - release.published_at).total_seconds() / 3600.0)
    return Candidate(
        release=release,
        parsed=parsed,
        fmt=fmt,
        custom_score=0,  # filled by the decision engine (needs the profile)
        protocol=protocol or detect_protocol(release),
        indexer_priority=indexer_priority,
        seeders=release.seeders,
        age_hours=age_hours,
        size_bytes=release.size_bytes,
    )
