"""Open Library provider (free, open, dumpable — the primary source).

Endpoints: /api/books (ISBN lookup), /works/{key}.json (work detail),
/search.json (search), covers.openlibrary.org (covers).
"""

from __future__ import annotations

import re
from typing import Any

from libarr.metadata.cache import cached_fetch
from libarr.metadata.providers import BaseProvider, BookMetadata, ProviderError

_API = "https://openlibrary.org"
_COVERS = "https://covers.openlibrary.org"
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


class OpenLibraryProvider(BaseProvider):
    name = "openlibrary"

    def lookup_by_isbn(self, isbn13: str) -> BookMetadata | None:
        """Resolve an ISBN to canonical metadata, or None when unknown."""

        def fetch() -> dict[str, Any]:
            return self._get_json(
                f"{_API}/api/books",
                bibkeys=f"ISBN:{isbn13}",
                jscmd="details",
                format="json",
            )

        try:
            payload = cached_fetch(
                self.session, self.name, "isbn", isbn13, fetch
            )
        except ProviderError:
            raise
        details = payload.get(f"ISBN:{isbn13}", {}).get("details")
        if not details:
            return None
        return self._normalize_details(details, isbn13)

    def get_work(self, work_key: str) -> BookMetadata | None:
        """Fetch a work by its OL key (e.g. 'OL123W')."""

        def fetch() -> dict[str, Any]:
            return self._get_json(f"{_API}/works/{work_key}.json")

        try:
            payload = cached_fetch(self.session, self.name, "work", work_key, fetch)
        except ProviderError:
            raise
        return self._normalize_details(payload, None)

    def search(self, query: str, limit: int = 20) -> list[BookMetadata]:
        """Search works by title/author/keywords (returns candidate list)."""

        def fetch() -> dict[str, Any]:
            return self._get_json(f"{_API}/search.json", q=query, limit=str(limit))

        try:
            payload = cached_fetch(self.session, self.name, "search", query, fetch)
        except ProviderError:
            raise
        results: list[BookMetadata] = []
        for doc in payload.get("docs", []):
            cover = None
            if doc.get("cover_i"):
                cover = f"{_COVERS}/b/id/{doc['cover_i']}-L.jpg"
            results.append(
                BookMetadata(
                    title=doc.get("title"),
                    authors=doc.get("author_name") or [],
                    subjects=doc.get("subject") or [],
                    year=doc.get("first_publish_year"),
                    cover_url=cover,
                    work_key=str(doc.get("key", "")).removeprefix("/works/"),
                    isbn13=_first(doc.get("isbn") or [], isbn13=True),
                )
            )
        return results

    def _normalize_details(
        self, details: dict[str, Any], fallback_isbn: str | None
    ) -> BookMetadata:
        authors = [a.get("name", "") for a in details.get("authors", []) if a.get("name")]
        subjects = [s.get("name", "") for s in details.get("subjects", []) if s.get("name")]
        covers = details.get("covers") or []
        works = details.get("works") or []
        publish_date = str(details.get("publish_date", ""))
        year_match = _YEAR_RE.search(publish_date)
        isbn13 = _first(details.get("isbn_13") or [], isbn13=True) or fallback_isbn

        return BookMetadata(
            title=details.get("title"),
            authors=authors,
            description=_description(details.get("description")),
            subjects=subjects,
            year=int(year_match.group(1)) if year_match else None,
            publisher=_first_name(details.get("publishers")),
            page_count=details.get("number_of_pages"),
            cover_url=f"{_COVERS}/b/id/{covers[0]}-L.jpg" if covers else None,
            work_key=str(works[0].get("key", "")).removeprefix("/works/") if works else None,
            isbn13=isbn13,
        )


def _description(raw: object) -> str | None:
    """OL descriptions are either a string or {"type": ..., "value": ...}."""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        value = raw.get("value")
        return value if isinstance(value, str) else None
    return None


def _first_name(items: list[Any] | None) -> str | None:
    if not items:
        return None
    first = items[0]
    return first.get("name") if isinstance(first, dict) else str(first)


def _first(isbns: list[Any], *, isbn13: bool) -> str | None:
    target_len = 13 if isbn13 else 10
    for raw in isbns:
        digits = re.sub(r"[^0-9Xx]", "", str(raw))
        if len(digits) == target_len:
            return digits
    return None
