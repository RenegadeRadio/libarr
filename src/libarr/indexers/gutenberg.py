"""Project Gutenberg as a first-class indexer (plan 2.1.4 — legal by default).

Gutenberg's official search endpoint serves the gutendex-style JSON:
https://www.gutenberg.org/ebooks/search/?query=...&format=json
Download URLs are direct EPUB/MOBI/text files — the whole point: acquisition
works out of the box with zero piracy.
"""

from __future__ import annotations

from typing import Any, cast

import httpx

from libarr.indexers.base import IndexerError, Release
from libarr.indexers.torznab import USER_AGENT

SEARCH_URL = "https://www.gutenberg.org/ebooks/search"


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

    def _get(self, params: dict[str, str]) -> dict[str, Any]:
        try:
            resp = httpx.get(
                SEARCH_URL,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=30.0,
            )
            resp.raise_for_status()
            return cast(dict[str, Any], resp.json())
        except httpx.HTTPError as exc:
            raise IndexerError(f"{self.name}: {exc}") from exc

    def search(self, q: str) -> list[Release]:
        return self._parse(self._get({"query": q, "format": "json"}))

    def recent(self, limit: int = 50) -> list[Release]:
        return self._parse(
            self._get({"sort_order": "updated", "format": "json", "page_size": str(limit)})
        )

    def _parse(self, payload: dict[str, Any]) -> list[Release]:
        releases: list[Release] = []
        for result in payload.get("results", []):
            formats = result.get("formats") or {}
            epub = formats.get("application/epub+zip") or formats.get("application/epub")
            download = epub or next(iter(formats.values()), None)
            authors = result.get("authors") or []
            author = authors[0].get("name") if authors else None
            book_id = result.get("id")
            title = result.get("title") or ""
            releases.append(
                Release(
                    title=title,
                    indexer_name=self.name,
                    download_url=str(download) if download else "",
                    guid=f"gutenberg:{book_id}",
                    author=author,
                    format="EPUB" if epub else None,
                    page_url=f"https://www.gutenberg.org/ebooks/{book_id}" if book_id else None,
                )
            )
        return releases
