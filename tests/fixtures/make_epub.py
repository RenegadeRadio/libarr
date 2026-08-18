"""Generate tiny EPUB fixtures for tests (no network, no real files)."""

from __future__ import annotations

import uuid
from pathlib import Path

from ebooklib import epub


def make_epub(
    path: str | Path,
    title: str,
    author: str | None = None,
    isbn: str | None = None,
    language: str = "en",
    cover_bytes: bytes | None = None,
) -> Path:
    """Write a minimal valid EPUB to `path`."""
    book = epub.EpubBook()
    book.set_identifier(isbn or str(uuid.uuid4()))
    book.set_title(title)
    book.set_language(language)
    if author:
        book.add_author(author)
    if cover_bytes:
        book.set_cover("cover.jpg", cover_bytes)

    chapter = epub.EpubHtml(title="Chapter 1", file_name="c1.xhtml", lang=language)
    chapter.content = "<h1>Chapter 1</h1><p>Fixture text.</p>"
    book.add_item(chapter)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(target), book)
    return target
