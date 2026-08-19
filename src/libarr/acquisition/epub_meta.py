"""Fast EPUB metadata extraction.

Reads only META-INF/container.xml and the OPF package document from the zip —
orders of magnitude faster than a full ebooklib parse, which matters when
scanning 10k+ book libraries (plan §8 performance guard).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import TypedDict

CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
DC_NS = "http://purl.org/dc/elements/1.1/"


class OpfMetadata(TypedDict):
    title: str | None
    authors: list[str]
    language: str | None
    publisher: str | None
    identifiers: list[str]
    isbn: str | None


def read_opf_metadata(path: Path) -> OpfMetadata | None:
    """Extract title/authors/language/publisher/ISBN from an EPUB's OPF, or None."""
    try:
        with zipfile.ZipFile(path) as archive:
            container = ET.fromstring(archive.read("META-INF/container.xml"))
            rootfile = container.find(f".//{{{CONTAINER_NS}}}rootfile")
            if rootfile is None:
                return None
            opf_path = rootfile.get("full-path")
            if not opf_path:
                return None
            opf = ET.fromstring(archive.read(opf_path))
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError, ValueError):
        return None

    dc = {"dc": DC_NS}

    def _text(tag: str) -> str | None:
        el = opf.find(f".//dc:{tag}", dc)
        return el.text.strip() if el is not None and el.text and el.text.strip() else None

    identifiers = [
        el.text.strip() for el in opf.findall(".//dc:identifier", dc) if el.text and el.text.strip()
    ]
    authors = [a.text.strip() for a in opf.findall(".//dc:creator", dc) if a.text]

    return {
        "title": _text("title"),
        "authors": authors,
        "language": _text("language"),
        "publisher": _text("publisher"),
        "identifiers": identifiers,
        "isbn": _pick_isbn(identifiers),
    }


_ISBN_SCHEME_RE = re.compile(r"isbn", re.IGNORECASE)
_ISBN_TEXT_RE = re.compile(r"ISBN(?:-1[03])?[:\s]*([0-9Xx][0-9\- ]{8,17}[0-9Xx])", re.IGNORECASE)


def _pick_isbn(identifiers: list[str]) -> str | None:
    """Prefer an identifier whose scheme or text marks it as an ISBN."""
    for identifier in identifiers:
        if _ISBN_SCHEME_RE.search(identifier.split(":")[0] if ":" in identifier else ""):
            return re.sub(r"[^0-9Xx]", "", identifier.split(":", 1)[-1])
    for identifier in identifiers:
        match = _ISBN_TEXT_RE.search(identifier)
        if match:
            return re.sub(r"[^0-9Xx]", "", match.group(1))
    # Bare identifier that is exactly ISBN-shaped ("9780385171683").
    for identifier in identifiers:
        digits = re.sub(r"[^0-9Xx]", "", identifier)
        if len(digits) in (10, 13):
            return digits
    return None
