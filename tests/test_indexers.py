"""Phase 2.1 — indexer layer: Torznab/Newznab client, registry, legal built-ins."""

import pytest
import respx
from httpx import Response

from libarr.indexers.base import IndexerError, detect_format
from libarr.indexers.gutenberg import GutenbergIndexer
from libarr.indexers.openlibrary import OpenLibraryIndexer
from libarr.indexers.registry import build_indexer
from libarr.indexers.torznab import TorznabIndexer
from libarr.models import Indexer


def _torznab_rss(
    title="Dune - Frank Herbert (1965) EPUB", size="12345678", seeders="42", peers="50", guid="t1"
) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <title>Test Indexer</title>
    <item>
      <title>{title}</title>
      <guid isPermaLink="false">{guid}</guid>
      <link>http://tracker.example/download/1</link>
      <pubDate>Fri, 01 Jan 2026 00:00:00 +0000</pubDate>
      <description>Dune by Frank Herbert</description>
      <enclosure url="http://tracker.example/download/1.torrent"
                    length="{size}" type="application/x-bittorrent"/>
      <torznab:attr name="size" value="{size}"/>
      <torznab:attr name="seeders" value="{seeders}"/>
      <torznab:attr name="peers" value="{peers}"/>
    </item>
  </channel>
</rss>"""


_CAPS_XML = """<?xml version="1.0"?>
<caps>
  <server title="Test Indexer" version="1.0"/>
  <limits max="100" default="100"/>
  <searching>
    <search available="yes" supportedParams="q"/>
  </searching>
  <categories>
    <category id="7000" name="Books">
      <subcat id="7010" name="Ebooks"/>
      <subcat id="7030" name="Foreign"/>
    </category>
  </categories>
</caps>"""


@respx.mock
def test_torznab_search_parses_releases():
    respx.get(url__startswith="http://idx.example/api").mock(
        return_value=Response(200, text=_torznab_rss())
    )
    idx = TorznabIndexer(name="test", url="http://idx.example", api_key="k", categories="7000,7010")

    releases = idx.search("dune")

    assert len(releases) == 1
    r = releases[0]
    assert r.title == "Dune - Frank Herbert (1965) EPUB"
    assert r.indexer_name == "test"
    assert r.size_bytes == 12345678
    assert r.seeders == 42
    assert r.peers == 50
    assert r.download_url == "http://tracker.example/download/1.torrent"
    assert r.guid == "t1"
    assert r.format == "EPUB"
    assert r.published_at is not None


@respx.mock
def test_torznab_search_uses_correct_query_params():
    route = respx.get(url__startswith="http://idx.example/api").mock(
        return_value=Response(200, text=_torznab_rss())
    )
    idx = TorznabIndexer(
        name="test", url="http://idx.example/", api_key="secret", categories="7000,7010"
    )

    idx.search("dune book")

    request = route.calls[0].request
    assert request.url.params["t"] == "search"
    assert request.url.params["q"] == "dune book"
    assert request.url.params["cat"] == "7000,7010"
    assert request.url.params["apikey"] == "secret"


@respx.mock
def test_torznab_caps_introspection():
    respx.get(url__startswith="http://idx.example/api").mock(
        return_value=Response(200, text=_CAPS_XML)
    )
    idx = TorznabIndexer(name="test", url="http://idx.example", api_key="k", categories="7000")

    caps = idx.caps()

    assert caps["title"] == "Test Indexer"
    assert 7000 in caps["categories"]
    assert 7010 in caps["categories"]
    assert caps["search_available"] is True


@respx.mock
def test_torznab_error_raises_indexer_error():
    respx.get(url__startswith="http://idx.example/api").mock(
        return_value=Response(500, text="boom")
    )
    idx = TorznabIndexer(name="test", url="http://idx.example", api_key="k", categories="7000")
    with pytest.raises(IndexerError):
        idx.search("dune")


GUTENBERG_JSON = {
    "count": 1,
    "next": None,
    "previous": None,
    "results": [
        {
            "id": 11,
            "title": "Alice's Adventures in Wonderland",
            "authors": [{"name": "Carroll, Lewis", "birth_year": 1832, "death_year": 1898}],
            "subjects": ["Fantasy literature", "Children's stories"],
            "languages": [{"code": "en", "name": "English"}],
            "copyright": False,
            "media_type": "Text",
            "download_count": 5432,
            "formats": {
                "application/epub+zip": "https://www.gutenberg.org/ebooks/11.epub3.images",
                "application/x-mobipocket-ebook": "https://www.gutenberg.org/ebooks/11.kf8.images",
                "text/plain; charset=us-ascii": "https://www.gutenberg.org/files/11/11-0.txt",
            },
        }
    ],
}

# The real official endpoint shape: [query, titles, authors, links, …] with a
# "Displaying results" header row at index 0 (captured live, 2026-08-19).
GUTENBERG_LEGACY_JSON = [
    "alice",
    ["Displaying results 1-25", "Alice's Adventures in Wonderland", "A Romance of Billy-Goat Hill"],
    [None, "Carroll, Lewis", "Alice Caldwell Hegan Rice"],
    [None, "/ebooks/11.json", "/ebooks/6635.json"],
]


@respx.mock
def test_gutenberg_search_parses_legacy_array():
    respx.get(url__startswith="https://www.gutenberg.org/ebooks/search/").mock(
        return_value=Response(200, json=GUTENBERG_LEGACY_JSON)
    )
    idx = GutenbergIndexer(name="Project Gutenberg")

    releases = idx.search("alice")

    assert len(releases) == 2
    r = releases[0]
    assert r.title == "Alice's Adventures in Wonderland"
    assert r.author == "Carroll, Lewis"
    assert r.download_url == "https://www.gutenberg.org/ebooks/11.epub3.images"
    assert r.guid == "gutenberg:11"
    assert r.format == "EPUB"


@respx.mock
def test_gutenberg_search_parses_releases():
    respx.get(url__startswith="https://www.gutenberg.org/ebooks/search").mock(
        return_value=Response(200, json=GUTENBERG_JSON)
    )
    idx = GutenbergIndexer(name="Project Gutenberg")

    releases = idx.search("alice")

    assert len(releases) == 1
    r = releases[0]
    assert r.title == "Alice's Adventures in Wonderland"
    assert r.author == "Carroll, Lewis"
    assert r.year is None  # Gutenberg search JSON carries no publication year
    assert r.download_url == "https://www.gutenberg.org/ebooks/11.epub3.images"
    assert r.format == "EPUB"
    assert r.isbn is None


OL_SEARCH_JSON = {
    "numFound": 1,
    "docs": [
        {
            "key": "/works/OL123W",
            "title": "Alice's Adventures in Wonderland",
            "author_name": ["Lewis Carroll"],
            "first_publish_year": 1865,
            "ia": ["alicesadventures0000unse_v7d2"],
        }
    ],
}


@respx.mock
def test_openlibrary_search_parses_releases():
    respx.get(url__startswith="https://openlibrary.org/search.json").mock(
        return_value=Response(200, json=OL_SEARCH_JSON)
    )
    idx = OpenLibraryIndexer(name="Open Library")

    releases = idx.search("alice")

    assert len(releases) == 1
    r = releases[0]
    assert r.title == "Alice's Adventures in Wonderland"
    assert r.author == "Lewis Carroll"
    assert r.year == 1865
    assert r.download_url == (
        "https://archive.org/download/alicesadventures0000unse_v7d2/alicesadventures0000unse_v7d2.epub"
    )
    assert r.format == "EPUB"


def test_registry_builds_clients():
    row = Indexer(
        name="Books", kind="torznab", url="http://idx.example", api_key="k", categories="7000"
    )
    client = build_indexer(row)
    assert isinstance(client, TorznabIndexer)
    assert client.name == "Books"

    gutenberg = build_indexer(Indexer(name="PG", kind="gutenberg"))
    assert isinstance(gutenberg, GutenbergIndexer)

    ol = build_indexer(Indexer(name="OL", kind="openlibrary"))
    assert isinstance(ol, OpenLibraryIndexer)


def test_registry_rejects_unknown_kind():
    row = Indexer(name="X", kind="bogus")
    with pytest.raises(IndexerError):
        build_indexer(row)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Dune.epub", "EPUB"),
        ("Dune (2021) EPUB", "EPUB"),
        ("[ebook] Dune - AZW3", "AZW3"),
        ("Dune mobi retag", "MOBI"),
        ("Dune scanned PDF", "PDF"),
        ("Dune AUDIOBOOK M4B", "M4B"),
        ("Dune MP3 64kbps", "MP3"),
        ("Dune fb2 russian", "FB2"),
        ("Dune", None),
    ],
)
def test_detect_format(title, expected):
    assert detect_format(title) == expected
