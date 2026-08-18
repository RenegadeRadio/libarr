"""Book-flavored release-name / filename parser (plan §2.2, Task 1.3).

Extracts title, author, year, series, series position, edition hints and
ISBNs from ebook filenames — the first line of defense in the import
pipeline, before metadata matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

STRONG_EXTENSIONS = {
    "epub", "mobi", "azw", "azw3", "azw4", "pdf",
    "fb2", "cbz", "cbr", "m4b", "mp3", "aax",
}
WEAK_EXTENSIONS = {"txt"}
EBOOK_EXTENSIONS = STRONG_EXTENSIONS | WEAK_EXTENSIONS

# "Unabridged", "Annotated", … distinguish an edition qualifier from a series name.
EDITION_KEYWORDS = {
    "unabridged", "abridged", "annotated", "illustrated", "revised", "expanded",
    "special edition", "collectors edition", "collector's edition", "2nd edition",
    "3rd edition", "deluxe", "omnibus", "uncut",
}

_YEAR_RE = re.compile(r"[\(\[](\d{4})[\)\]]")
_ISBN13_RE = re.compile(r"^\d{13}$")
_ISBN10_RE = re.compile(r"^\d{9}[\dX]$")
_SEP_RE = re.compile(r"\s*[-–—]\s*")


@dataclass
class ParsedName:
    title: str | None = None
    author: str | None = None
    year: int | None = None
    series: str | None = None
    series_position: int | None = None
    edition_hint: str | None = None
    isbn: str | None = None


def parse_book_filename(filename: str) -> ParsedName | None:
    """Parse an ebook filename into structured parts, or None if it isn't one."""
    name = filename.strip()
    if not name:
        return None

    dot = name.rfind(".")
    ext = name[dot + 1 :].lower() if dot > 0 else ""
    stem = name[:dot] if dot > 0 else name
    if ext not in EBOOK_EXTENSIONS:
        return None

    # Drop [group]/[quality] tags, but never [1965]-style year brackets.
    stem = re.sub(r"\[(?!\d{4}\])[^\]]*\]", " ", stem)
    parts = [p.strip() for p in _SEP_RE.split(stem) if p.strip()]
    if not parts:
        return None

    result = ParsedName()

    # ISBN prefix (e.g. "9780061120084 - The Road - Cormac McCarthy.epub").
    isbn = _find_isbn(parts[0])
    if isbn is not None:
        result.isbn = isbn
        parts = parts[1:]
        if not parts:
            return None

    # Year from any part, e.g. "Stephen King (1990)" or "Dune [1965]".
    cleaned: list[str] = []
    for part in parts:
        match = _YEAR_RE.search(part)
        if match and result.year is None:
            result.year = int(match.group(1))
        part = _YEAR_RE.sub("", part).strip()
        if part:
            cleaned.append(part)
    parts = cleaned
    if not parts:
        return None

    if len(parts) == 1:
        if ext in WEAK_EXTENSIONS:
            return None  # "notes.txt" is not a book; "Neuromancer.mobi" is.
        result.title = _clean_title(parts[0])
        return result if result.title else None

    if len(parts) == 2:
        result.title = _clean_title(parts[0])
        result.author = _clean_author(parts[1])
        return result if result.title else None

    # Three or more parts: last is the author; the middle decides the shape.
    author = _clean_author(parts[-1])
    middle = parts[1].lower()

    if re.fullmatch(r"\d{1,3}", parts[1]):
        result.series = _clean_title(parts[0])
        result.series_position = int(parts[1])
        result.title = _clean_title(" - ".join(parts[2:-1]) if len(parts) > 3 else parts[2])
    elif middle in EDITION_KEYWORDS:
        result.edition_hint = parts[1]
        result.title = _clean_title(parts[0])
    else:
        result.series = _clean_title(parts[0])
        result.title = _clean_title(" - ".join(parts[1:-1]))

    result.author = author
    return result if result.title else None


def _find_isbn(part: str) -> str | None:
    digits = re.sub(r"[\s\-]", "", part)
    if _ISBN13_RE.match(digits) or _ISBN10_RE.match(digits):
        return digits
    return None


def _clean_title(text: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", text.replace("_", " ")).strip(" .")
    return cleaned or None


def _clean_author(text: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", text.replace("_", " ")).strip(" .")
    return cleaned or None
