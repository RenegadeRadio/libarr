"""OPDS 1.2 catalog feeds (plan Task 1.8) — the e-reader gateway.

Every e-reader and reading app (KOReader, Kobo, PocketBook, iOS/Android
readers) speaks OPDS 1.2: root navigation feed → author/collection feeds →
book entries with acquisition links. Search is wired through OpenSearch.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast
from xml.etree.ElementTree import Element, SubElement, tostring

from sqlalchemy import select
from sqlalchemy.orm import Session

from libarr.library.search import search_books
from libarr.models import Author, Book

ATOM = "http://www.w3.org/2005/Atom"
DC = "http://purl.org/dc/terms/"
OPENSEARCH = "http://a9.com/-/spec/opensearch/1.1/"

CATALOG_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"
OPENSEARCH_TYPE = "application/opensearchdescription+xml"
ACQUISITION_REL = "http://opds-spec.org/acquisition"
IMAGE_REL = "http://opds-spec.org/image"

MEDIA_TYPES = {
    "epub": "application/epub+zip",
    "pdf": "application/pdf",
    "mobi": "application/x-mobipocket-ebook",
    "azw3": "application/x-mobipocket-ebook",
    "fb2": "application/x-fictionbook+xml",
    "cbz": "application/vnd.comicbook+zip",
    "cbr": "application/vnd.comicbook-rar",
    "m4b": "audio/mp4",
    "mp3": "audio/mpeg",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else _now()


def _text(parent: Element, tag: str, value: str) -> None:
    child = SubElement(parent, tag)
    child.text = value


def _link(parent: Element, rel: str, href: str, type_: str | None = None) -> None:
    link = SubElement(parent, f"{{{ATOM}}}link")
    link.set("rel", rel)
    link.set("href", href)
    if type_:
        link.set("type", type_)


def _feed(title: str, feed_id: str) -> Element:
    feed = Element(f"{{{ATOM}}}feed")
    _text(feed, f"{{{ATOM}}}id", feed_id)
    _text(feed, f"{{{ATOM}}}title", title)
    _text(feed, f"{{{ATOM}}}updated", _now())
    author = SubElement(feed, f"{{{ATOM}}}author")
    _text(author, f"{{{ATOM}}}name", "Libarr")
    _link(feed, "self", "/opds", CATALOG_TYPE)
    _link(feed, "start", "/opds", CATALOG_TYPE)
    return feed


def _entry(feed: Element, title: str, entry_id: str, updated: str | None = None) -> Element:
    entry = SubElement(feed, f"{{{ATOM}}}entry")
    _text(entry, f"{{{ATOM}}}title", title)
    _text(entry, f"{{{ATOM}}}id", entry_id)
    _text(entry, f"{{{ATOM}}}updated", updated or _now())
    return entry


def _render(feed: Element) -> bytes:
    return cast(bytes, tostring(feed, encoding="utf-8", xml_declaration=True))


def root_feed() -> bytes:
    feed = _feed("Libarr", "urn:libarr:opds:root")
    _link(feed, "search", "/opds/search.xml", OPENSEARCH_TYPE)

    sections = [
        ("Authors", "urn:libarr:opds:authors", "/opds/authors",
         "Browse the library by author."),
        ("New Books", "urn:libarr:opds:new", "/opds/new",
         "Recently added books."),
    ]
    for title, entry_id, href, description in sections:
        entry = _entry(feed, title, entry_id)
        _text(entry, f"{{{ATOM}}}content", description)
        _link(entry, "subsection", href, CATALOG_TYPE)
    return _render(feed)


def authors_feed(session: Session) -> bytes:
    feed = _feed("Authors", "urn:libarr:opds:authors")
    for author in session.scalars(select(Author).order_by(Author.name)).all():
        entry = _entry(feed, author.name, f"urn:libarr:author:{author.id}")
        _text(
            entry, f"{{{ATOM}}}content",
            f"{len(author.books)} book(s) by {author.name}",
        )
        _link(entry, "subsection", f"/opds/authors/{author.id}", CATALOG_TYPE)
    return _render(feed)


def author_books_feed(session: Session, author_id: int) -> bytes | None:
    author = session.get(Author, author_id)
    if author is None:
        return None
    feed = _feed(f"Books by {author.name}", f"urn:libarr:author:{author_id}")
    for book in sorted(author.books, key=lambda b: b.title):
        _book_entry(feed, book)
    return _render(feed)


def new_feed(session: Session, limit: int = 50) -> bytes:
    feed = _feed("New Books", "urn:libarr:opds:new")
    books = session.scalars(
        select(Book).order_by(Book.date_added.desc()).limit(limit)
    ).all()
    for book in books:
        _book_entry(feed, book)
    return _render(feed)


def search_feed(session: Session, query: str) -> bytes:
    feed = _feed(f"Search: {query}", "urn:libarr:opds:search")
    books, _, _ = search_books(session, q=query, limit=50)
    for book in books:
        _book_entry(feed, book)
    return _render(feed)


def search_description() -> bytes:
    root = Element(f"{{{OPENSEARCH}}}OpenSearchDescription")
    _text(root, f"{{{OPENSEARCH}}}ShortName", "Libarr")
    _text(root, f"{{{OPENSEARCH}}}Description", "Search the Libarr library")
    url = SubElement(root, f"{{{OPENSEARCH}}}Url")
    url.set("type", CATALOG_TYPE)
    url.set("template", "/opds/search?q={searchTerms}")
    return cast(bytes, tostring(root, encoding="utf-8", xml_declaration=True))


def _book_entry(feed: Element, book: Book) -> None:
    entry = _entry(
        feed, book.title, f"urn:libarr:book:{book.id}", _stamp(book.date_added)
    )
    if book.author is not None:
        author = SubElement(entry, f"{{{ATOM}}}author")
        _text(author, f"{{{ATOM}}}name", book.author.name)
    if book.language:
        _text(entry, f"{{{DC}}}language", book.language)
    if book.year:
        _text(entry, f"{{{DC}}}issued", str(book.year))
    if book.description:
        _text(entry, f"{{{ATOM}}}content", book.description[:2000])
    if book.cover_path:
        _link(entry, IMAGE_REL, f"/api/v1/covers/{book.id}", "image/jpeg")

    file_row = next((f for e in book.editions for f in e.files), None)
    if file_row is not None:
        _link(
            entry,
            ACQUISITION_REL,
            f"/api/v1/books/{book.id}/file",
            MEDIA_TYPES.get(file_row.format.lower(), "application/octet-stream"),
        )
