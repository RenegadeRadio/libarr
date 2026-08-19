"""Metadata providers: shared types, error type and HTTP plumbing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import httpx
from sqlalchemy.orm import Session

from libarr import __version__

USER_AGENT = f"libarr/{__version__} (+https://github.com/RenegadeRadio/libarr)"


class ProviderError(Exception):
    """Raised when a metadata provider cannot serve a request."""


@dataclass
class BookMetadata:
    """Canonical, provider-agnostic book metadata (plan §4.3 flow D)."""

    title: str | None = None
    authors: list[str] = field(default_factory=list)
    description: str | None = None
    subjects: list[str] = field(default_factory=list)
    year: int | None = None
    publisher: str | None = None
    page_count: int | None = None
    language: str | None = None
    cover_url: str | None = None
    work_key: str | None = None
    edition_key: str | None = None
    isbn13: str | None = None


class BaseProvider:
    """Shared httpx plumbing for all providers (UA header, status checks)."""

    name = "base"

    def __init__(self, session: Session, client: httpx.Client | None = None) -> None:
        self.session = session
        self.client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20.0)

    def _get_json(self, url: str, **params: str) -> dict[str, Any]:
        try:
            response = self.client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name}: {exc}") from exc
        if response.status_code != 200:
            raise ProviderError(f"{self.name}: HTTP {response.status_code} for {url}")
        return cast(dict[str, Any], response.json())

    def close(self) -> None:
        self.client.close()
