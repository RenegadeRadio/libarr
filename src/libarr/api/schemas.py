"""Pydantic response/request schemas for the API v1."""

from __future__ import annotations

from datetime import date, datetime

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
