"""Standard Ebooks as a first-class indexer via its OPDS feeds (plan 2.1.4).

Standard Ebooks publishes curated, DRM-free, typographically-polished editions
of the public-domain canon, served as OPDS 1.2 feeds — parsing them with
feedparser is trivial and their EPUBs are excellent quality.
"""

from __future__ import annotations

from datetime import UTC, datetime

import feedparser  # type: ignore[import-untyped]
import httpx

from libarr.indexers.base import IndexerError, Release
from libarr.indexers.torznab import USER_AGENT

SEARCH_URL = "https://standardebooks.org/opds/search"
ALL_URL = "https://standardebooks.org/opds/all"


class StandardEbooksIndexer:
    kind = "standardebooks"

    def __init__(
        self,
        *,
        name: str = "Standard Ebooks",
        url: str | None = None,
        api_key: str | None = None,
        categories: str = "",
    ) -> None:
        self.name = name

    def _fetch(self, url: str, params: dict[str, str] | None = None) -> str:
        try:
            resp = httpx.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:
            raise IndexerError(f"{self.name}: {exc}") from exc

    def search(self, q: str) -> list[Release]:
        return self._parse(self._fetch(SEARCH_URL, {"query": q}))

    def recent(self, limit: int = 100) -> list[Release]:
        return self._parse(self._fetch(ALL_URL))

    def _parse(self, xml: str) -> list[Release]:
        feed = feedparser.parse(xml)
        releases: list[Release] = []
        for entry in feed.entries:
            links = entry.get("links", [])
            download = next(
                (
                    link
                    for link in links
                    if "acquisition" in link.get("rel", "") and "epub" in link.get("type", "")
                ),
                None,
            )
            if download is None:
                download = next(
                    (link for link in links if "acquisition" in link.get("rel", "")), None
                )
            author = None
            for person in entry.get("authors", []):
                author = person.get("name")
                break
            published = entry.get("updated_parsed") or entry.get("published_parsed")
            published_dt = (
                datetime(
                    published[0], published[1], published[2],
                    published[3], published[4], published[5],
                    tzinfo=UTC,
                )
                if published
                else None
            )
            releases.append(
                Release(
                    title=entry.get("title") or "",
                    indexer_name=self.name,
                    download_url=download.get("href") if download else "",
                    guid=entry.get("id") or entry.get("link") or "",
                    author=author,
                    format="EPUB" if download and "epub" in download.get("type", "") else None,
                    published_at=published_dt,
                    page_url=entry.get("link"),
                )
            )
        return releases
