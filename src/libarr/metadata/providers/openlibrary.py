"""Open Library provider (free, open, dumpable — the primary source).

ISBN lookups resolve in three cached hops, mirroring the real data model:
edition details (`/api/books`) → work (`/works/{key}.json`) → author names
(`/authors/{key}.json`). Edition records carry no authors/subjects — those
live on the work, which is why a single-endpoint design (like Readarr's)
loses data. Endpoints: /api/books, /works, /authors, /search.json, covers.
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
        """Resolve an ISBN to canonical metadata (edition merged with its work)."""

        def fetch() -> dict[str, Any]:
            return self._get_json(
                f"{_API}/api/books",
                bibkeys=f"ISBN:{isbn13}",
                jscmd="details",
                format="json",
            )

        payload = cached_fetch(self.session, self.name, "isbn", isbn13, fetch)
        details = payload.get(f"ISBN:{isbn13}", {}).get("details")
        if not details:
            return None

        edition_meta = self._normalize_details(details, isbn13)
        works = details.get("works") or []
        if works:
            work_key = str(works[0].get("key", "")).removeprefix("/works/")
            try:
                work_meta = self.get_work(work_key)
            except ProviderError:
                work_meta = None  # edition data alone beats nothing (anti-Readarr rule)
            if work_meta is not None:
                return _merge(edition_meta, work_meta)
        return edition_meta

    def get_work(self, work_key: str) -> BookMetadata | None:
        """Fetch a work by its OL key (e.g. 'OL123W'), including author names."""

        def fetch() -> dict[str, Any]:
            return self._get_json(f"{_API}/works/{work_key}.json")

        payload = cached_fetch(self.session, self.name, "work", work_key, fetch)
        return self._normalize_details(payload, None)

    def search(self, query: str, limit: int = 20) -> list[BookMetadata]:
        """Search works by title/author/keywords (returns candidate list)."""

        def fetch() -> dict[str, Any]:
            return self._get_json(f"{_API}/search.json", q=query, limit=str(limit))

        payload = cached_fetch(self.session, self.name, "search", query, fetch)
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
        authors = self._author_names(details)
        # Work records carry subjects as plain strings; edition records as dicts.
        subjects: list[str] = []
        for subject in details.get("subjects", []):
            if isinstance(subject, str):
                subjects.append(subject)
            elif isinstance(subject, dict) and subject.get("name"):
                subjects.append(subject["name"])
        covers = details.get("covers") or []
        works = details.get("works") or []
        publish_date = str(details.get("publish_date", ""))
        year_match = _YEAR_RE.search(publish_date)
        if year_match is None:
            year_match = _YEAR_RE.search(str(details.get("first_publish_date", "")))
        isbn13 = _first(details.get("isbn_13") or [], isbn13=True) or fallback_isbn

        return BookMetadata(
            title=details.get("title"),
            authors=authors,
            description=_description(details.get("description")),
            subjects=subjects,
            year=int(year_match.group(1)) if year_match else None,
            publisher=_first_name(details.get("publishers")),
            page_count=details.get("number_of_pages"),
            language=_language_code(details.get("languages")),
            cover_url=f"{_COVERS}/b/id/{covers[0]}-L.jpg" if covers else None,
            work_key=str(works[0].get("key", "")).removeprefix("/works/") if works else None,
            isbn13=isbn13,
        )

    def _author_names(self, details: dict[str, Any]) -> list[str]:
        """Author names from entries; resolves /authors/{key}.json when absent (cached)."""
        names: list[str] = []
        for entry in details.get("authors") or []:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if name:
                names.append(name)
                continue
            author_obj = entry.get("author")
            key = author_obj.get("key") if isinstance(author_obj, dict) else None
            if not key:
                continue
            author_key = str(key).removeprefix("/authors/")

            def fetch(author_key: str = author_key) -> dict[str, Any]:
                return self._get_json(f"{_API}/authors/{author_key}.json")

            try:
                payload = cached_fetch(self.session, self.name, "author", author_key, fetch)
            except ProviderError:
                continue
            author_name = payload.get("name")
            if author_name:
                names.append(author_name)
        return names


def _merge(edition: BookMetadata, work: BookMetadata) -> BookMetadata:
    """Edition wins for physical facts; work wins for authors/subjects/description."""
    return BookMetadata(
        title=edition.title or work.title,
        authors=work.authors or edition.authors,
        description=work.description or edition.description,
        subjects=work.subjects or edition.subjects,
        year=edition.year or work.year,
        publisher=edition.publisher or work.publisher,
        page_count=edition.page_count or work.page_count,
        language=edition.language or work.language,
        cover_url=edition.cover_url or work.cover_url,
        work_key=edition.work_key or work.work_key,
        edition_key=edition.edition_key or work.edition_key,
        isbn13=edition.isbn13 or work.isbn13,
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


def _language_code(languages: list[Any] | None) -> str | None:
    if not languages:
        return None
    first = languages[0]
    key = first.get("key") if isinstance(first, dict) else str(first)
    if not key:
        return None
    code = str(key).rsplit("/", 1)[-1]
    return code or None


def _first(isbns: list[Any], *, isbn13: bool) -> str | None:
    target_len = 13 if isbn13 else 10
    for raw in isbns:
        digits = re.sub(r"[^0-9Xx]", "", str(raw))
        if len(digits) == target_len:
            return digits
    return None
