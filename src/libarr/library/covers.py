"""Cover serving (plan Task 1.10): local cache → EPUB extraction → provider.

Order matters: the on-disk cache is free, EPUB extraction is local, and the
provider URL (from last-known metadata_json) is the last resort — the same
resilience-first posture as the metadata layer.
"""

from __future__ import annotations

import json
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from libarr.config import Settings
from libarr.metadata.providers import USER_AGENT
from libarr.models import Book

CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
OPF_NS = "http://www.idpf.org/2007/opf"


def covers_dir() -> Path:
    path = Path(Settings().data_dir) / "covers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_cover(session: Session, book: Book) -> Path | None:
    """Return a local cover file for the book, fetching/extracting if needed."""
    cached = covers_dir() / f"{book.id}.jpg"
    if cached.is_file():
        return cached

    file_row = next((f for e in book.editions for f in e.files), None)
    if file_row is not None and file_row.format.lower() == "epub":
        data = extract_epub_cover(Path(file_row.path))
        if data:
            cached.write_bytes(data)
            return cached

    url = _cover_url(book)
    if url:
        try:
            data = _download(url)
        except httpx.HTTPError:
            data = None
        if data:
            cached.write_bytes(data)
            return cached
    return None


def cover_media_type(path: Path) -> str:
    """Sniff PNG vs JPEG from magic bytes."""
    with path.open("rb") as handle:
        magic = handle.read(8)
    return "image/png" if magic.startswith(b"\x89PNG") else "image/jpeg"


def _cover_url(book: Book) -> str | None:
    if not book.metadata_json:
        return None
    try:
        meta = json.loads(book.metadata_json)
    except json.JSONDecodeError:
        return None
    url = meta.get("cover_url")
    return url if isinstance(url, str) else None


def _download(url: str) -> bytes:
    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=20.0, follow_redirects=True
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def extract_epub_cover(epub_path: Path) -> bytes | None:
    """Pull the cover image out of an EPUB (OPF meta name=cover → manifest)."""
    try:
        with zipfile.ZipFile(epub_path) as archive:
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

    items: dict[str, tuple[str, str]] = {}
    for item in opf.findall(f".//{{{OPF_NS}}}item"):
        item_id = item.get("id")
        href = item.get("href")
        media_type = item.get("media-type") or ""
        if item_id and href:
            items[item_id] = (href, media_type)

    cover_id: str | None = None
    for meta in opf.findall(f".//{{{OPF_NS}}}meta"):
        if (meta.get("name") or "").lower() == "cover":
            cover_id = meta.get("content")
            break

    candidates: list[str] = []
    if cover_id and cover_id in items:
        candidates.append(cover_id)
    for item_id, (href, media_type) in items.items():
        if media_type.startswith("image/") and (
            "cover" in item_id.lower() or "cover" in href.lower()
        ):
            candidates.append(item_id)
    if not candidates:
        return None

    base_dir = urllib.parse.urljoin(opf_path, ".")
    for item_id in dict.fromkeys(candidates):
        href, _ = items[item_id]
        try:
            with zipfile.ZipFile(epub_path) as archive:
                return archive.read(urllib.parse.urljoin(base_dir, href))
        except (KeyError, OSError):
            continue
    return None
