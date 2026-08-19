"""Google Books provider (fallback source; optional API key via settings).

Google's `categories` feed our subjects facet (plan §4.4). No key required
for low volume, but LIBARR_GOOGLE_BOOKS_API_KEY enables a much higher quota.
"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx
from sqlalchemy.orm import Session

from libarr.metadata.cache import cached_fetch
from libarr.metadata.providers import BaseProvider, BookMetadata

_API = "https://www.googleapis.com/books/v1/volumes"
_YEAR_RE = re.compile(r"^(1[89]\d{2}|20\d{2})")


class GoogleBooksProvider(BaseProvider):
    name = "googlebooks"

    def __init__(self, session: Session, client: httpx.Client | None = None) -> None:
        super().__init__(session, client)
        self.api_key = os.environ.get("LIBARR_GOOGLE_BOOKS_API_KEY")

    def lookup_by_isbn(self, isbn13: str) -> BookMetadata | None:
        """Resolve an ISBN to canonical metadata, or None when unknown."""

        def fetch() -> dict[str, Any]:
            params: dict[str, str] = {"q": f"isbn:{isbn13}", "maxResults": "1"}
            if self.api_key:
                params = {**params, "key": self.api_key}
            return self._get_json(_API, **params)

        payload = cached_fetch(self.session, self.name, "isbn", isbn13, fetch)
        if not payload.get("items"):
            return None
        info = payload["items"][0].get("volumeInfo", {})

        year_match = _YEAR_RE.match(str(info.get("publishedDate", "")))
        edition_isbn13 = _industry_identifier(info, "ISBN_13")
        cover = None
        image_links = info.get("imageLinks")
        if isinstance(image_links, dict) and image_links.get("thumbnail"):
            cover = image_links["thumbnail"].split("&")[0]

        return BookMetadata(
            title=info.get("title"),
            authors=info.get("authors") or [],
            description=info.get("description"),
            subjects=info.get("categories") or [],
            year=int(year_match.group(1)) if year_match else None,
            publisher=info.get("publisher"),
            page_count=info.get("pageCount"),
            language=info.get("language"),
            cover_url=cover,
            isbn13=edition_isbn13 or None,
        )

    def search(self, q: str, limit: int = 40) -> list[BookMetadata]:
        """Subject/keyword search over volumes (plan 2.6.2, Google fallback).

        Returns lightweight works (title/authors/year/subjects) — used by
        discovery lists when Open Library is unavailable.
        """
        params: dict[str, str] = {"q": q, "maxResults": str(limit)}
        if self.api_key:
            params = {**params, "key": self.api_key}
        try:
            payload = self._get_json(_API, **params)
        except Exception:  # noqa: BLE001 — provider isolation
            return []
        works: list[BookMetadata] = []
        for item in payload.get("items") or []:
            info = item.get("volumeInfo") or {}
            year_match = _YEAR_RE.match(str(info.get("publishedDate", "")))
            works.append(
                BookMetadata(
                    title=info.get("title"),
                    authors=info.get("authors") or [],
                    subjects=info.get("categories") or [],
                    year=int(year_match.group(1)) if year_match else None,
                    language=info.get("language"),
                    work_key=str(item.get("id") or ""),
                )
            )
        return works


def _industry_identifier(info: dict[str, Any], kind: str) -> str | None:
    for identifier in info.get("industryIdentifiers") or []:
        if identifier.get("type") == kind:
            return re.sub(r"[^0-9Xx]", "", str(identifier.get("identifier", "")))
    return None
