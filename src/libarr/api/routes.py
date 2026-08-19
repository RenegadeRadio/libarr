"""HTTP API v1 routes: authors, books, file download, search."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from libarr.api.deps import get_session
from libarr.api.schemas import (
    AuthorDetail,
    AuthorOut,
    BookDetail,
    BookOut,
    BookPatch,
    SearchResult,
)
from libarr.api.serializers import (
    serialize_author,
    serialize_author_detail,
    serialize_book,
    serialize_book_detail,
)
from libarr.fts import reindex_book
from libarr.library.search import search_books
from libarr.metadata.matcher import STOPWORDS
from libarr.metadata.normalize import normalize_text
from libarr.models import Author, Book, Edition

router = APIRouter()

_MEDIA_TYPES = {
    "epub": "application/epub+zip",
    "pdf": "application/pdf",
    "mobi": "application/x-mobipocket-ebook",
    "azw3": "application/x-mobipocket-ebook",
    "fb2": "application/x-fictionbook+xml",
    "cbz": "application/vnd.comicbook+zip",
    "cbr": "application/vnd.comicbook-rar",
    "m4b": "audio/mp4",
    "mp3": "audio/mpeg",
}


def _book_options() -> tuple[Any, ...]:
    return (
        selectinload(Book.author),
        selectinload(Book.subjects),
        selectinload(Book.series),
        selectinload(Book.editions).selectinload(Edition.files),
    )


@router.get("/authors", response_model=list[AuthorOut])
def list_authors(
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    authors = session.scalars(
        select(Author)
        .options(selectinload(Author.books))
        .order_by(Author.name)
        .limit(limit)
        .offset(offset)
    ).all()
    return [serialize_author(a) for a in authors]


@router.get("/authors/{author_id}", response_model=AuthorDetail)
def get_author(author_id: int, session: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    author = session.get(Author, author_id, options=[selectinload(Author.books)])
    if author is None:
        raise HTTPException(status_code=404, detail="Author not found")
    return serialize_author_detail(author)


@router.get("/books", response_model=list[BookOut])
def list_books(
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    monitored: bool | None = None,
) -> list[dict[str, Any]]:
    stmt = select(Book).options(*_book_options()).order_by(Book.title)
    if monitored is not None:
        stmt = stmt.where(Book.monitored == monitored)
    books = session.scalars(stmt.limit(limit).offset(offset)).all()
    return [serialize_book(b) for b in books]


@router.get("/books/{book_id}", response_model=BookDetail)
def get_book(book_id: int, session: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    book = session.get(Book, book_id, options=list(_book_options()))
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return serialize_book_detail(book)


@router.patch("/books/{book_id}", response_model=BookDetail)
def patch_book(
    book_id: int, patch: BookPatch, session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    book = session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    changes = patch.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(book, field, value)
    if {"title", "subtitle", "description"} & changes.keys():
        reindex_book(session, book.id)

    session.commit()
    session.refresh(book)
    return serialize_book_detail(book)


@router.get("/books/{book_id}/file")
def book_file(book_id: int, session: Annotated[Session, Depends(get_session)]) -> FileResponse:
    book = session.get(
        Book, book_id,
        options=[selectinload(Book.editions).selectinload(Edition.files)],
    )
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    file_row = next((f for e in book.editions for f in e.files), None)
    if file_row is None or not Path(file_row.path).is_file():
        raise HTTPException(status_code=404, detail="No file available")
    path = Path(file_row.path)
    return FileResponse(
        path,
        media_type=_MEDIA_TYPES.get(file_row.format.lower()),
        filename=path.name,
    )


@router.get("/search", response_model=SearchResult)
def search(
    session: Annotated[Session, Depends(get_session)],
    q: str | None = None,
    genre: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    language: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    # Stopword-only queries carry no signal — treat them as no query.
    if q:
        tokens = [t for t in normalize_text(q).split() if t not in STOPWORDS]
        if not tokens:
            q = None
    if not any([q, genre, year_min is not None, year_max is not None, language]):
        raise HTTPException(status_code=400, detail="At least one search filter required")
    books, total, facets = search_books(
        session,
        q=q,
        genre=genre,
        year_min=year_min,
        year_max=year_max,
        language=language,
        limit=limit,
        offset=offset,
    )
    return {
        "total": total,
        "facets": facets,
        "results": [serialize_book(b) for b in books],
    }
