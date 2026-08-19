"""Pydantic response/request schemas for the API v1."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class SubjectOut(BaseModel):
    name: str
    slug: str
    source: str


class FileOut(BaseModel):
    id: int
    path: str
    format: str
    size_bytes: int


class EditionOut(BaseModel):
    id: int
    isbn13: str | None
    isbn10: str | None
    publisher: str | None
    published_at: date | None
    format: str | None
    files: list[FileOut]


class AuthorOut(BaseModel):
    id: int
    name: str
    book_count: int = 0


class AuthorDetail(BaseModel):
    id: int
    name: str
    sort_name: str | None
    biography: str | None
    ol_key: str | None
    monitored: bool = False
    book_count: int = 0


class BookOut(BaseModel):
    id: int
    title: str
    subtitle: str | None
    author_name: str | None
    year: int | None
    language: str | None
    monitored: bool
    cover_path: str | None
    series_title: str | None
    series_position: int | None
    subjects: list[str]
    formats: list[str]


class BookDetail(BookOut):
    description: str | None
    work_key: str | None
    page_count: int | None
    editions: list[EditionOut]


class BookPatch(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    description: str | None = None
    year: int | None = None
    language: str | None = None
    monitored: bool | None = None


class Facet(BaseModel):
    slug: str
    name: str
    count: int


class SearchResult(BaseModel):
    total: int
    facets: list[Facet]
    results: list[BookOut]


class ProgressPut(BaseModel):
    profile: str = Field(min_length=1, max_length=64)
    position: float = Field(ge=0.0, le=1.0)
    location: str | None = None


class ProgressOut(BaseModel):
    book_id: int
    profile: str
    position: float
    location: str | None
    updated_at: datetime


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)


class BootstrapBody(LoginBody):
    pass


class BootstrapStatus(BaseModel):
    needed: bool


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    api_key: str | None


class IndexerIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=32)
    url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=255)
    categories: str = Field(default="7000,7010,7030,7050", max_length=255)
    priority: int = Field(default=100, ge=0, le=1000)
    enabled: bool = True
    rss_enabled: bool = True


class IndexerOut(IndexerIn):
    id: int
    created_at: datetime


class IndexerTestResult(BaseModel):
    ok: bool
    caps: dict[str, Any] | None
    error: str | None


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=32)
    url: str | None = Field(default=None, max_length=512)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=255)
    api_key: str | None = Field(default=None, max_length=255)
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=1000)
    remote_path: str | None = Field(default=None, max_length=512)
    local_path: str | None = Field(default=None, max_length=512)


class ClientOut(ClientIn):
    id: int
    created_at: datetime


class ClientTestResult(BaseModel):
    ok: bool
    error: str | None


class AuthorPatch(BaseModel):
    monitored: bool


class HistoryOut(BaseModel):
    id: int
    book_id: int | None
    kind: str
    title: str
    details: str | None
    created_at: datetime


class DiscoveryWorkIn(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    author: str | None = Field(default=None, max_length=255)
    year: int | None = None
    subjects: list[str] = Field(default_factory=list)
    source: str = Field(default="discovery", max_length=32)
    source_key: str = Field(default="", max_length=255)


class DiscoveryWorkOut(DiscoveryWorkIn):
    pass


class DiscoveryImportBody(BaseModel):
    works: list[DiscoveryWorkIn]
    monitored: bool = True


class DiscoveryListIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    query: dict[str, Any]  # q/genre/year_min/year_max/language
    schedule_days: int = Field(default=7, ge=1, le=365)
    max_per_run: int = Field(default=10, ge=1, le=100)
    auto_monitor: bool = True
    enabled: bool = True


class DiscoveryListOut(BaseModel):
    id: int
    name: str
    query: dict[str, Any]
    schedule_days: int
    max_per_run: int
    auto_monitor: bool
    enabled: bool
    last_run_at: datetime | None
    created_at: datetime


class RequestIn(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    author: str | None = Field(default=None, max_length=255)
    isbn: str | None = Field(default=None, max_length=32)


class ConversionIn(BaseModel):
    target_format: str = Field(pattern=r"^(AZW3|KEPUB|PDF|MOBI)$")


class ConversionOut(BaseModel):
    id: int
    file_id: int
    target_format: str
    status: str
    output_path: str | None
    error: str | None
    created_at: datetime


class QueueOut(BaseModel):
    id: int
    book_id: int | None
    title: str
    indexer_name: str
    download_url: str | None
    format: str | None
    manual: bool
    status: str
    error: str | None
    created_at: datetime
