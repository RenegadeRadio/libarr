"""Phase 1.8 — OPDS 1.2 catalog (the e-reader gateway)."""

import xml.etree.ElementTree as ET

from sqlalchemy import select

from libarr.db import session_factory
from libarr.fts import reindex_book
from libarr.models import Author, Book, Edition, File, Subject
from tests.fixtures.make_epub import make_epub

ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/terms/}"


def _seed(session, tmp_path):
    herbert = Author(name="Frank Herbert")
    king = Author(name="Stephen King")
    session.add_all([herbert, king])
    session.flush()

    dune = Book(author_id=herbert.id, title="Dune", year=1965, language="eng")
    stand = Book(author_id=king.id, title="The Stand", year=1990)
    session.add_all([dune, stand])
    session.flush()

    dune_edition = Edition(book_id=dune.id, isbn13="9780441172719", format="EPUB")
    session.add(dune_edition)
    session.flush()

    epub_path = make_epub(tmp_path / "Dune.epub", "Dune", "Frank Herbert")
    session.add(
        File(
            edition_id=dune_edition.id,
            path=str(epub_path),
            format="EPUB",
            size_bytes=epub_path.stat().st_size,
            sha256="y" * 64,
        )
    )
    session.add(
        Subject(book_id=dune.id, name="Science Fiction", slug="science-fiction", source="user")
    )
    session.commit()
    for book in (dune, stand):
        reindex_book(session, book.id)
    session.commit()


def _entries(feed: ET.Element) -> list[ET.Element]:
    return feed.findall(f"{ATOM}entry")


def _link_href(entry: ET.Element, rel: str) -> str | None:
    for link in entry.findall(f"{ATOM}link"):
        if link.get("rel") == rel:
            return link.get("href")
    return None


def test_opds_root_navigation(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        _seed(session, tmp_path)

    resp = client.get("/opds")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/atom+xml;profile=opds-catalog")
    feed = ET.fromstring(resp.content)
    assert feed.findtext(f"{ATOM}title") == "Libarr"

    entry_titles = [e.findtext(f"{ATOM}title") for e in _entries(feed)]
    assert "Authors" in entry_titles
    assert "New Books" in entry_titles

    # OpenSearch link on the root feed.
    search_link = None
    for link in feed.findall(f"{ATOM}link"):
        if link.get("rel") == "search":
            search_link = link
    assert search_link is not None
    assert search_link.get("type") == "application/opensearchdescription+xml"
    assert search_link.get("href") == "/opds/search.xml"


def test_opds_authors_feed(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        _seed(session, tmp_path)

    resp = client.get("/opds/authors")
    feed = ET.fromstring(resp.content)

    titles = {e.findtext(f"{ATOM}title") for e in _entries(feed)}
    assert titles == {"Frank Herbert", "Stephen King"}

    # Each author entry links to its acquisition feed.
    herbert = next(e for e in _entries(feed) if e.findtext(f"{ATOM}title") == "Frank Herbert")
    href = _link_href(herbert, "subsection")
    assert href is not None and href.startswith("/opds/authors/")


def test_opds_author_books_feed(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        _seed(session, tmp_path)
        author_id = session.scalars(select(Author).where(Author.name == "Frank Herbert")).one().id

    resp = client.get(f"/opds/authors/{author_id}")
    feed = ET.fromstring(resp.content)
    entries = _entries(feed)
    assert len(entries) == 1

    dune = entries[0]
    assert dune.findtext(f"{ATOM}title") == "Dune"
    assert dune.findtext(f"{ATOM}author/{ATOM}name") == "Frank Herbert"
    assert dune.findtext(f"{DC}language") == "eng"
    assert dune.findtext(f"{DC}issued") == "1965"

    acquisition = _link_href(dune, "http://opds-spec.org/acquisition")
    assert acquisition == "/api/v1/books/1/file"

    acquisition_link = next(
        link
        for link in dune.findall(f"{ATOM}link")
        if link.get("rel") == "http://opds-spec.org/acquisition"
    )
    assert acquisition_link.get("type") == "application/epub+zip"


def test_opds_new_feed_newest_first(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        _seed(session, tmp_path)

    resp = client.get("/opds/new")
    feed = ET.fromstring(resp.content)

    titles = [e.findtext(f"{ATOM}title") for e in _entries(feed)]
    assert titles == ["The Stand", "Dune"]  # The Stand added second → newest


def test_opds_search_description(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        _seed(session, tmp_path)

    resp = client.get("/opds/search.xml")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/opensearchdescription+xml")
    assert "opensearch" in resp.text.lower()
    assert "/opds/search?q={searchTerms}" in resp.text


def test_opds_search_returns_book_entries(client, tmp_path):
    client, db = client
    with session_factory(db)() as session:
        _seed(session, tmp_path)

    resp = client.get("/opds/search", params={"q": "dune"})
    feed = ET.fromstring(resp.content)

    titles = [e.findtext(f"{ATOM}title") for e in _entries(feed)]
    assert titles == ["Dune"]
