"""HTTP API v1 routes: authors, books, file download, search, OPDS.

Every route here is behind forced authentication (plan Task 1.11): the
routers declare `dependencies=[Depends(require_user)]`, so cookie, X-Api-Key
and HTTP Basic credentials all work. Health + auth endpoints live outside.
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from libarr.acquisition.import_pipeline import default_import_hook
from libarr.acquisition.wanted import wanted_cutoff, wanted_missing
from libarr.api.auth import require_user
from libarr.api.deps import get_session
from libarr.api.schemas import (
    AuthorDetail,
    AuthorOut,
    AuthorPatch,
    BookDetail,
    BookOut,
    BookPatch,
    ClientIn,
    ClientOut,
    ClientTestResult,
    ConversionIn,
    ConversionOut,
    DiscoveryImportBody,
    DiscoveryListIn,
    DiscoveryListOut,
    DiscoveryWorkOut,
    HistoryOut,
    IndexerIn,
    IndexerOut,
    IndexerTestResult,
    ProgressOut,
    ProgressPut,
    QueueOut,
    RequestIn,
    SearchResult,
    SendToKindleIn,
)
from libarr.api.serializers import (
    serialize_author,
    serialize_author_detail,
    serialize_book,
    serialize_book_detail,
    serialize_client,
    serialize_history,
    serialize_indexer,
)
from libarr.clients.base import DownloadError
from libarr.clients.registry import CLIENT_KINDS, build_client
from libarr.config import Settings
from libarr.discovery import DiscoveryWork, evaluate_lists, import_works, search_works
from libarr.fts import reindex_book
from libarr.history import record
from libarr.indexers.base import IndexerError
from libarr.indexers.registry import SUPPORTED_KINDS, build_indexer
from libarr.library.covers import cover_media_type, resolve_cover
from libarr.library.opds import (
    CATALOG_TYPE,
    MEDIA_TYPES,
    OPENSEARCH_TYPE,
    author_books_feed,
    authors_feed,
    new_feed,
    root_feed,
    search_description,
    search_feed,
)
from libarr.library.search import search_books
from libarr.metadata.matcher import STOPWORDS
from libarr.metadata.normalize import normalize_text
from libarr.models import (
    Author,
    Book,
    ConversionJob,
    DiscoveryList,
    DownloadClientRow,
    Edition,
    HistoryEvent,
    Indexer,
    QueueItem,
    ReadingProgress,
    User,
)
from libarr.tasks.download_watch import process_queue
from libarr.tasks.rss import rss_sync
from libarr.tasks.search import search_now

router = APIRouter(dependencies=[Depends(require_user)])


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


@router.patch("/authors/{author_id}", response_model=AuthorDetail)
def patch_author(
    author_id: int,
    body: AuthorPatch,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    """Monitor/unmonitor an author (plan 2.5.3 — author-level defaults)."""
    author = session.get(Author, author_id, options=[selectinload(Author.books)])
    if author is None:
        raise HTTPException(status_code=404, detail="Author not found")
    author.monitored = body.monitored
    session.commit()
    session.refresh(author)
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
        Book,
        book_id,
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
        media_type=MEDIA_TYPES.get(file_row.format.lower()),
        filename=path.name,
    )


@router.get("/books/{book_id}/cover")
@router.get("/covers/{book_id}")
def book_cover(book_id: int, session: Annotated[Session, Depends(get_session)]) -> FileResponse:
    book = session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    cover = resolve_cover(session, book)
    if cover is None:
        raise HTTPException(status_code=404, detail="No cover available")
    return FileResponse(cover, media_type=cover_media_type(cover))


@router.get("/books/{book_id}/progress", response_model=ProgressOut)
def get_progress(
    book_id: int,
    session: Annotated[Session, Depends(get_session)],
    profile: str = Query("default", min_length=1, max_length=64),
) -> dict[str, Any]:
    book = session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    row = session.get(ReadingProgress, (book_id, profile))
    if row is None:
        raise HTTPException(status_code=404, detail="No progress recorded")
    return {
        "book_id": row.book_id,
        "profile": row.profile,
        "position": row.position,
        "location": row.location,
        "updated_at": row.updated_at,
    }


@router.put("/books/{book_id}/progress", response_model=ProgressOut)
def put_progress(
    book_id: int,
    body: ProgressPut,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    book = session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    row = session.get(ReadingProgress, (book_id, body.profile))
    if row is None:
        row = ReadingProgress(book_id=book_id, profile=body.profile)
        session.add(row)
    row.position = body.position
    row.location = body.location
    session.commit()
    session.refresh(row)
    return {
        "book_id": row.book_id,
        "profile": row.profile,
        "position": row.position,
        "location": row.location,
        "updated_at": row.updated_at,
    }


# --- Indexers (plan 2.1.2) --------------------------------------------------


@router.get("/indexers", response_model=list[IndexerOut])
def list_indexers(
    session: Annotated[Session, Depends(get_session)],
) -> list[dict[str, Any]]:
    rows = session.scalars(select(Indexer).order_by(Indexer.priority, Indexer.name)).all()
    return [serialize_indexer(row) for row in rows]


@router.post("/indexers", response_model=IndexerOut)
def create_indexer(
    body: IndexerIn, session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    if body.kind not in SUPPORTED_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown indexer kind. Supported: {', '.join(SUPPORTED_KINDS)}",
        )
    exists = session.scalars(select(Indexer).where(Indexer.name == body.name)).first()
    if exists is not None:
        raise HTTPException(status_code=409, detail="Indexer name already exists")
    row = Indexer(**body.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return serialize_indexer(row)


@router.get("/indexers/{indexer_id}", response_model=IndexerOut)
def get_indexer(
    indexer_id: int, session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    row = session.get(Indexer, indexer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Indexer not found")
    return serialize_indexer(row)


@router.put("/indexers/{indexer_id}", response_model=IndexerOut)
def update_indexer(
    indexer_id: int,
    body: IndexerIn,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    row = session.get(Indexer, indexer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Indexer not found")
    if body.kind not in SUPPORTED_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown indexer kind. Supported: {', '.join(SUPPORTED_KINDS)}",
        )
    for field, value in body.model_dump().items():
        setattr(row, field, value)
    session.commit()
    session.refresh(row)
    return serialize_indexer(row)


@router.delete("/indexers/{indexer_id}")
def delete_indexer(
    indexer_id: int, session: Annotated[Session, Depends(get_session)]
) -> dict[str, str]:
    row = session.get(Indexer, indexer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Indexer not found")
    session.delete(row)
    session.commit()
    return {"status": "ok"}


@router.post("/indexers/{indexer_id}/test", response_model=IndexerTestResult)
def test_indexer(
    indexer_id: int, session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    row = session.get(Indexer, indexer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Indexer not found")
    try:
        client = build_indexer(row)
        caps_fn = getattr(client, "caps", None)
        caps = caps_fn() if callable(caps_fn) else {}
        return {"ok": True, "caps": caps, "error": None}
    except IndexerError as exc:
        return {"ok": False, "caps": None, "error": str(exc)}


@router.post("/system/rss-sync")
def trigger_rss_sync(
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    """Manual RSS-sync trigger (the scheduler will call rss_sync on cadence)."""
    stats = rss_sync(session)
    queued = sum(v for v in stats.values() if isinstance(v, int))
    return {"indexers": stats, "queued": queued}


# --- Download clients (plan 2.2) --------------------------------------------


@router.get("/clients", response_model=list[ClientOut])
def list_clients(
    session: Annotated[Session, Depends(get_session)],
) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(DownloadClientRow).order_by(DownloadClientRow.priority, DownloadClientRow.name)
    ).all()
    return [serialize_client(row) for row in rows]


@router.post("/clients", response_model=ClientOut)
def create_client(
    body: ClientIn, session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    if body.kind not in CLIENT_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown client kind. Supported: {', '.join(CLIENT_KINDS)}",
        )
    exists = session.scalars(
        select(DownloadClientRow).where(DownloadClientRow.name == body.name)
    ).first()
    if exists is not None:
        raise HTTPException(status_code=409, detail="Client name already exists")
    row = DownloadClientRow(**body.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return serialize_client(row)


@router.get("/clients/{client_id}", response_model=ClientOut)
def get_client(client_id: int, session: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    row = session.get(DownloadClientRow, client_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Download client not found")
    return serialize_client(row)


@router.put("/clients/{client_id}", response_model=ClientOut)
def update_client(
    client_id: int,
    body: ClientIn,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    row = session.get(DownloadClientRow, client_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Download client not found")
    if body.kind not in CLIENT_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown client kind. Supported: {', '.join(CLIENT_KINDS)}",
        )
    for field, value in body.model_dump().items():
        setattr(row, field, value)
    session.commit()
    session.refresh(row)
    return serialize_client(row)


@router.delete("/clients/{client_id}")
def delete_client(
    client_id: int, session: Annotated[Session, Depends(get_session)]
) -> dict[str, str]:
    row = session.get(DownloadClientRow, client_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Download client not found")
    session.delete(row)
    session.commit()
    return {"status": "ok"}


@router.post("/clients/{client_id}/test", response_model=ClientTestResult)
def test_client(
    client_id: int, session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    row = session.get(DownloadClientRow, client_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Download client not found")
    try:
        client = build_client(row)
        ok = client.test()
        return {"ok": ok, "error": None}
    except DownloadError as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/system/process-queue")
def trigger_process_queue(
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    """Manual queue cycle: grab queued items, watch for completions."""
    stats = process_queue(session, import_hook=default_import_hook)
    return {"stats": stats}


@router.get("/queue", response_model=list[QueueOut])
def list_queue(
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Active queue: grabbed downloads plus manual-download bookmarks."""
    items = session.scalars(select(QueueItem).order_by(QueueItem.id.desc()).limit(limit)).all()
    return [
        {
            "id": item.id,
            "book_id": item.book_id,
            "title": item.title,
            "indexer_name": item.indexer_name,
            "download_url": item.download_url,
            "format": item.format,
            "manual": item.manual,
            "status": item.status,
            "error": item.error,
            "created_at": item.created_at,
        }
        for item in items
    ]


# --- Wanted / history (plan 2.5) --------------------------------------------


@router.get("/wanted/missing", response_model=list[BookOut])
def wanted_missing_endpoint(
    session: Annotated[Session, Depends(get_session)],
) -> list[dict[str, Any]]:
    return [serialize_book(book) for book in wanted_missing(session)]


@router.get("/wanted/cutoff", response_model=list[BookOut])
def wanted_cutoff_endpoint(
    session: Annotated[Session, Depends(get_session)],
) -> list[dict[str, Any]]:
    return [serialize_book(book) for book in wanted_cutoff(session)]


@router.post("/books/{book_id}/search")
def book_search_now(
    book_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(require_user)],
) -> dict[str, Any]:
    """Search every indexer for this book right now; queue the winner."""
    book = session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return search_now(session, book, user=user)


@router.get("/history", response_model=list[HistoryOut])
def history(
    session: Annotated[Session, Depends(get_session)],
    kind: str | None = None,
    book_id: int | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    stmt = select(HistoryEvent).order_by(HistoryEvent.created_at.desc(), HistoryEvent.id.desc())
    if kind:
        stmt = stmt.where(HistoryEvent.kind == kind)
    if book_id is not None:
        stmt = stmt.where(HistoryEvent.book_id == book_id)
    events = session.scalars(stmt.limit(limit)).all()
    return [serialize_history(event) for event in events]


# --- Discovery (plan 2.6) ----------------------------------------------------


def _serialize_discovery_list(row: DiscoveryList) -> dict[str, Any]:
    try:
        query = _json.loads(row.query)
    except _json.JSONDecodeError:
        query = {}
    return {
        "id": row.id,
        "name": row.name,
        "query": query,
        "schedule_days": row.schedule_days,
        "max_per_run": row.max_per_run,
        "auto_monitor": row.auto_monitor,
        "enabled": row.enabled,
        "last_run_at": row.last_run_at,
        "created_at": row.created_at,
    }


@router.get("/discovery", response_model=list[DiscoveryWorkOut])
def discovery_search(
    session: Annotated[Session, Depends(get_session)],
    q: str | None = None,
    genre: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    language: str | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Live discovery preview: works matching the query from providers."""
    if not any([q, genre]):
        raise HTTPException(status_code=400, detail="q or genre required")
    return [
        {
            "title": w.title,
            "author": w.author,
            "year": w.year,
            "subjects": w.subjects,
            "source": w.source,
            "source_key": w.source_key,
        }
        for w in search_works(
            session,
            q=q,
            genre=genre,
            year_min=year_min,
            year_max=year_max,
            language=language,
            limit=limit,
        )
    ]


@router.post("/discovery/import")
def discovery_import(
    body: DiscoveryImportBody, session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    from libarr.discovery import DiscoveryWork

    works = [
        DiscoveryWork(
            title=w.title,
            author=w.author,
            year=w.year,
            subjects=w.subjects,
            source=w.source,
            source_key=w.source_key,
        )
        for w in body.works
    ]
    added = import_works(session, works, monitored=body.monitored)
    return {"added": added}


@router.get("/discovery-lists", response_model=list[DiscoveryListOut])
def list_discovery_lists(
    session: Annotated[Session, Depends(get_session)],
) -> list[dict[str, Any]]:
    rows = session.scalars(select(DiscoveryList).order_by(DiscoveryList.name)).all()
    return [_serialize_discovery_list(row) for row in rows]


@router.post("/discovery-lists", response_model=DiscoveryListOut)
def create_discovery_list(
    body: DiscoveryListIn, session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    row = DiscoveryList(
        name=body.name,
        query=_json.dumps(body.query),
        schedule_days=body.schedule_days,
        max_per_run=body.max_per_run,
        auto_monitor=body.auto_monitor,
        enabled=body.enabled,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _serialize_discovery_list(row)


@router.delete("/discovery-lists/{list_id}")
def delete_discovery_list(
    list_id: int, session: Annotated[Session, Depends(get_session)]
) -> dict[str, str]:
    row = session.get(DiscoveryList, list_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Discovery list not found")
    session.delete(row)
    session.commit()
    return {"status": "ok"}


@router.post("/system/discovery-lists")
def trigger_discovery_lists(
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    """Evaluate every enabled discovery list (scheduler will own cadence)."""
    stats = evaluate_lists(session)
    return {"lists": stats}


@router.get("/calendar")
def calendar(
    session: Annotated[Session, Depends(get_session)],
    years_back: int = Query(1, ge=0, le=5),
) -> list[dict[str, Any]]:
    """Upcoming/new releases for monitored authors (year granularity)."""
    from libarr.calendar import calendar_events

    return calendar_events(session, years_back=years_back)


# --- Requests / conversion (Phase 3) -----------------------------------------


@router.post("/requests")
def create_request(
    body: RequestIn,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(require_user)],
) -> dict[str, Any]:
    """Overseerr-style: request a book → auto-add (monitored) → search now."""
    book = None
    if body.isbn:
        from libarr.metadata.providers.openlibrary import OpenLibraryProvider

        meta = OpenLibraryProvider(session).lookup_by_isbn(body.isbn)
        if meta is not None and meta.title:
            works = [
                DiscoveryWork(
                    title=meta.title,
                    author=meta.authors[0] if meta.authors else None,
                    year=meta.year,
                    subjects=meta.subjects or [],
                    source="openlibrary",
                    source_key=meta.work_key or body.isbn,
                )
            ]
            import_works(session, works, monitored=True)
            book = _find_book(session, meta.title, meta.authors[0] if meta.authors else None)
    if book is None:
        works = search_works(session, q=body.title, genre=None, limit=1)
        if works:
            import_works(session, works, monitored=True)
            book = _find_book(session, works[0].title, works[0].author)
    if book is None:
        raise HTTPException(status_code=404, detail="Could not resolve the requested book")

    record(session, kind="request", title=book.title, book_id=book.id, details="user request")
    session.commit()
    result = search_now(session, book, user=user)
    return {"status": "ok", "book_id": book.id, "title": book.title, **result}


def _find_book(session: Session, title: str, author: str | None) -> Book | None:
    from libarr.metadata.normalize import normalize_text

    books = session.scalars(select(Book)).all()
    for book in books:
        if normalize_text(book.title) == normalize_text(title) and (
            author is None
            or (book.author and normalize_text(book.author.name) == normalize_text(author))
        ):
            return book
    return None


@router.get("/conversions", response_model=list[ConversionOut])
def list_conversions(
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    jobs = session.scalars(
        select(ConversionJob).order_by(ConversionJob.id.desc()).limit(limit)
    ).all()
    return [
        {
            "id": job.id,
            "file_id": job.file_id,
            "target_format": job.target_format,
            "status": job.status,
            "output_path": job.output_path,
            "error": job.error,
            "created_at": job.created_at,
        }
        for job in jobs
    ]


@router.post("/books/{book_id}/convert", response_model=ConversionOut)
def enqueue_book_conversion(
    book_id: int,
    body: ConversionIn,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    """Convert the book's best imported file to a device format."""
    from libarr.acquisition.wanted import best_imported_format
    from libarr.conversion import enqueue_conversion

    book = session.get(Book, book_id, options=[selectinload(Book.editions)])
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    best = best_imported_format(session, book)
    if best is None:
        raise HTTPException(status_code=400, detail="Book has no imported files")
    file_row = None
    for edition in book.editions:
        for file_row in edition.files:
            if file_row.format == best:
                break
        if file_row and file_row.format == best:
            break
    if file_row is None:
        raise HTTPException(status_code=404, detail="No importable file found")
    job = enqueue_conversion(session, file_row, body.target_format)
    return {
        "id": job.id,
        "file_id": job.file_id,
        "target_format": job.target_format,
        "status": job.status,
        "output_path": job.output_path,
        "error": job.error,
        "created_at": job.created_at,
    }


@router.post("/books/{book_id}/send-to-kindle")
def send_book_to_kindle(
    book_id: int,
    body: SendToKindleIn,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    """Email the book's best imported file to a @kindle.com address."""
    from libarr.acquisition.wanted import best_imported_format
    from libarr.kindle import KindleError, send_to_kindle

    book = session.get(Book, book_id, options=[selectinload(Book.editions)])
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    best = best_imported_format(session, book)
    if best is None:
        raise HTTPException(status_code=400, detail="Book has no imported files")
    file_path = None
    for edition in book.editions:
        for file_row in edition.files:
            if file_row.format == best:
                file_path = file_row.path
                break
        if file_path:
            break
    if not file_path:
        raise HTTPException(status_code=400, detail="No importable file found")

    try:
        send_to_kindle(
            Settings(),
            to=body.to,
            file_path=Path(file_path),
            title=book.title,
        )
    except KindleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"sent": True, "to": body.to, "title": book.title}


# --- OPDS 1.2 catalog (Task 1.8) -------------------------------------------
# Served at the root (no /api/v1 prefix): e-readers expect /opds.


opds_router = APIRouter(dependencies=[Depends(require_user)])


@opds_router.get("/opds")
def opds_root() -> Response:
    return Response(content=root_feed(), media_type=CATALOG_TYPE)


@opds_router.get("/opds/authors")
def opds_authors(session: Annotated[Session, Depends(get_session)]) -> Response:
    return Response(content=authors_feed(session), media_type=CATALOG_TYPE)


@opds_router.get("/opds/authors/{author_id}")
def opds_author(author_id: int, session: Annotated[Session, Depends(get_session)]) -> Response:
    feed = author_books_feed(session, author_id)
    if feed is None:
        raise HTTPException(status_code=404, detail="Author not found")
    return Response(content=feed, media_type=CATALOG_TYPE)


@opds_router.get("/opds/new")
def opds_new(session: Annotated[Session, Depends(get_session)]) -> Response:
    return Response(content=new_feed(session), media_type=CATALOG_TYPE)


@opds_router.get("/opds/search.xml")
def opds_search_description() -> Response:
    return Response(content=search_description(), media_type=OPENSEARCH_TYPE)


@opds_router.get("/opds/search")
def opds_search(q: str, session: Annotated[Session, Depends(get_session)]) -> Response:
    return Response(content=search_feed(session, q), media_type=CATALOG_TYPE)


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
