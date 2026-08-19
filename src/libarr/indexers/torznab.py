"""Torznab/Newznab indexer client (plan 2.1.1).

The de-facto *Arr indexer protocol: works with Prowlarr, Jackett, NZBHydra2
and most private trackers/usenet indexers. One client class serves both
Torznab (torrents) and Newznab (usenet) — they differ only in categories.

Parsing is ElementTree-based on purpose: feedparser collapses repeated
namespaced elements (multiple <torznab:attr> tags) into a single lossy dict.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from libarr.indexers.base import (
    IndexerError,
    Release,
    as_int,
    detect_format,
    year_from_title,
)

USER_AGENT = "libarr/0.1 (+https://github.com/RenegadeRadio/libarr)"
TORZNAB_NS = "http://torznab.com/schemas/2015/feed"


def _parse_pubdate(text: str) -> datetime | None:
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class TorznabIndexer:
    kind = "torznab"

    def __init__(
        self,
        *,
        name: str,
        url: str | None = None,
        api_key: str | None = None,
        categories: str = "7000,7010,7030,7050",
    ) -> None:
        self.name = name
        self.url = (url or "").rstrip("/")
        self.api_key = api_key or ""
        self.categories = categories

    def _get(self, params: dict[str, Any]) -> str:
        if self.api_key:
            params = {**params, "apikey": self.api_key}
        try:
            resp = httpx.get(
                f"{self.url}/api",
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=20.0,
            )
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:
            raise IndexerError(f"{self.name}: {exc}") from exc

    def search(self, q: str) -> list[Release]:
        return self._parse(self._get({"t": "search", "q": q, "cat": self.categories}))

    def recent(self, limit: int = 100) -> list[Release]:
        return self._parse(
            self._get({"t": "search", "cat": self.categories, "limit": limit, "extended": 1})
        )

    def caps(self) -> dict[str, Any]:
        """Capability introspection: server title, search availability, categories."""
        xml = self._get({"t": "caps"})
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise IndexerError(f"{self.name}: invalid caps response") from exc
        server = root.find("server")
        search_el = root.find("searching/search")
        categories: set[int] = set()
        for cat in root.iter("category"):
            cid = cat.get("id")
            if cid and cid.isdigit():
                categories.add(int(cid))
        for subcat in root.iter("subcat"):
            cid = subcat.get("id")
            if cid and cid.isdigit():
                categories.add(int(cid))
        return {
            "title": server.get("title") if server is not None else None,
            "search_available": (
                search_el is not None and search_el.get("available") == "yes"
            ),
            "categories": sorted(categories),
        }

    def _parse(self, xml: str) -> list[Release]:
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise IndexerError(f"{self.name}: unparseable feed") from exc
        releases: list[Release] = []
        for item in root.iter("item"):
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            guid_el = item.find("guid")
            guid = (guid_el.text if guid_el is not None and guid_el.text else link) or ""
            pubdate = item.findtext("pubDate")
            published = _parse_pubdate(pubdate) if pubdate else None

            size: int | None = None
            seeders: int | None = None
            peers: int | None = None
            enclosure_href: str | None = None
            enclosure_len: str | None = None
            for child in item:
                if child.tag == "enclosure":
                    enclosure_href = child.get("url") or child.get("href") or enclosure_href
                    enclosure_len = child.get("length") or enclosure_len
                elif child.tag == f"{{{TORZNAB_NS}}}attr":
                    name = child.get("name")
                    value = child.get("value")
                    if name == "size":
                        size = as_int(value)
                    elif name == "seeders":
                        seeders = as_int(value)
                    elif name == "peers":
                        peers = as_int(value)
            if size is None:
                size = as_int(enclosure_len)

            releases.append(
                Release(
                    title=title,
                    indexer_name=self.name,
                    download_url=enclosure_href or link,
                    guid=guid,
                    year=year_from_title(title),
                    format=detect_format(title),
                    size_bytes=size,
                    seeders=seeders,
                    peers=peers,
                    published_at=published,
                )
            )
        return releases
