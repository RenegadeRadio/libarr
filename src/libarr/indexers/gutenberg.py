"""Project Gutenberg as a first-class indexer (plan 2.1.4 — legal by default).

Gutenberg's official search endpoint serves a compact legacy JSON array:
    [query, [titles…], [authors…], ["/ebooks/11.json"…], …]
(titles[0] is a "Displaying results" header row). Some mirrors serve the
gutendex-style object shape, which we also accept. Download URLs are direct
EPUB files — acquisition works out of the box, zero piracy.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from libarr.indexers.base import IndexerError, Release
from libarr.indexers.torznab import USER_AGENT

SEARCH_URL = "https://www.gutenberg.org/ebooks/search/"


class GutenbergIndexer:
    kind = "gutenberg"

    def __init__(
        self,
        *,
        name: str = "Project Gutenberg",
        url: str | None = None,
        api_key: str | None = None,
        categories: str = "",
    ) -> None:
        self.name = name

    def _get(self, params: dict[str, str]) -> Any:
        try:
            resp = httpx.get(
                SEARCH_URL,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise IndexerError(f"{self.name}: {exc}") from exc

    def search(self, q: str) -> list[Release]:
        return self._parse(self._get({"query": q, "format": "json"}))

    def recent(self, limit: int = 50) -> list[Release]:
        # No query = the default "most popular" listing; sort_order is not
        # accepted by the legacy JSON endpoint (400), so we page the default.
        return self._parse(self._get({"format": "json", "page_size": str(limit)}))

    def _parse(self, payload: Any) -> list[Release]:
        if isinstance(payload, dict):
            return self._parse_gutendex(payload)
        if not isinstance(payload, list) or len(payload) < 4:
            return []
        releases: list[Release] = []
        titles, authors, links = payload[1], payload[2], payload[3]
        for title, author, link in zip(titles, authors, links, strict=False):
            if not title or str(title).startswith("Displaying results"):
                continue
            book_id: str | None = None
            if link:
                match = re.search(r"/ebooks/(\d+)\.json", str(link))
                if match:
                    book_id = match.group(1)
            if not book_id:
                continue
            releases.append(
                Release(
                    title=str(title),
                    indexer_name=self.name,
                    download_url=f"https://www.gutenberg.org/ebooks/{book_id}.epub3.images",
                    guid=f"gutenberg:{book_id}",
                    author=str(author) if author else None,
                    format="EPUB",
                    page_url=f"https://www.gutenberg.org/ebooks/{book_id}",
                )
            )
        return releases

    def _parse_gutendex(self, payload: dict[str, Any]) -> list[Release]:
        releases: list[Release] = []
        for result in payload.get("results", []):
            formats = result.get("formats") or {}
            epub = formats.get("application/epub+zip") or formats.get("application/epub")
            download = epub or next(iter(formats.values()), None)
            authors = result.get("authors") or []
            author = authors[0].get("name") if authors else None
            book_id = result.get("id")
            releases.append(
                Release(
                    title=str(result.get("title") or ""),
                    indexer_name=self.name,
                    download_url=str(download) if download else "",
                    guid=f"gutenberg:{book_id}",
                    author=str(author) if author else None,
                    format="EPUB" if epub else None,
                    page_url=f"https://www.gutenberg.org/ebooks/{book_id}" if book_id else None,
                )
            )
        return releases
