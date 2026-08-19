"""Open Library as a first-class legal indexer (plan 2.1.4).

Open Library's search API is stable and free; public-domain works carry
Internet Archive identifiers whose direct EPUBs are downloadable at
https://archive.org/download/{ia}/{ia}.epub. This replaced the Standard
Ebooks adapter after their OPDS feeds moved behind auth (401s, 2026-08).
"""

from __future__ import annotations

from typing import Any, cast

import httpx

from libarr.indexers.base import IndexerError, Release
from libarr.indexers.torznab import USER_AGENT

SEARCH_URL = "https://openlibrary.org/search.json"
_FIELDS = "key,title,author_name,first_publish_year,ia"


class OpenLibraryIndexer:
    kind = "openlibrary"

    def __init__(
        self,
        *,
        name: str = "Open Library",
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
        return self._parse(self._get({"q": q, "limit": "50", "fields": _FIELDS}))

    def recent(self, limit: int = 50) -> list[Release]:
        return self._parse(
            self._get(
                {"q": "subject:fiction", "sort": "new", "limit": str(limit), "fields": _FIELDS}
            )
        )

    def _parse(self, payload: dict[str, Any]) -> list[Release]:
        releases: list[Release] = []
        for doc in payload.get("docs", []):
            ia_list = doc.get("ia") or []
            ia = ia_list[0] if ia_list else None
            if not ia:
                continue  # no download available
            authors = doc.get("author_name") or []
            key = doc.get("key")
            releases.append(
                Release(
                    title=str(doc.get("title") or ""),
                    indexer_name=self.name,
                    download_url=f"https://archive.org/download/{ia}/{ia}.epub",
                    guid=f"ia:{ia}",
                    author=str(authors[0]) if authors else None,
                    year=doc.get("first_publish_year"),
                    format="EPUB",
                    page_url=f"https://openlibrary.org{key}" if key else None,
                )
            )
        return releases
