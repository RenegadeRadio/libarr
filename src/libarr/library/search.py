"""Full-text + faceted search over the library (plan §4.4, Task 1.7b).

The user-requested genre/keyword discovery: FTS5 keyword query over
titles/authors/descriptions/subjects, faceted by genre (subject slugs),
with year range and language filters. Returns (books, total, facets).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from libarr.metadata.matcher import STOPWORDS
from libarr.metadata.normalize import normalize_text
from libarr.models import Book, Edition


def search_books(
    session: Session,
    *,
    q: str | None = None,
    genre: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    language: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Book], int, list[dict[str, Any]]]:
    """Search the library; returns (books, total count, genre facets)."""
    clauses: list[str] = []
    params: dict[str, Any] = {}

    if q:
        tokens = [t for t in normalize_text(q).split() if t not in STOPWORDS]
        if tokens:
            clauses.append("book_fts MATCH :q")
            params["q"] = " AND ".join(f'"{t}"' for t in tokens)
    if genre:
        clauses.append("b.id IN (SELECT book_id FROM subjects WHERE slug = :genre)")
        params["genre"] = genre
    if year_min is not None:
        clauses.append("b.year >= :year_min")
        params["year_min"] = year_min
    if year_max is not None:
        clauses.append("b.year <= :year_max")
        params["year_max"] = year_max
    if language:
        clauses.append("b.language = :language")
        params["language"] = language

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    joins = "FROM book_fts f JOIN books b ON b.id = f.rowid"

    total = session.execute(
        text(f"SELECT COUNT(*) {joins}{where}"), params
    ).scalar_one()

    facets = [
        {"slug": slug, "name": name, "count": count}
        for slug, name, count in session.execute(
            text(
                f"SELECT s.slug, s.name, COUNT(*) AS c FROM subjects s "
                f"JOIN books b ON b.id = s.book_id "
                f"JOIN book_fts f ON f.rowid = s.book_id{where} "
                f"GROUP BY s.slug, s.name ORDER BY c DESC, s.name LIMIT 15"
            ),
            params,
        ).all()
    ]

    rows = session.execute(
        text(
            f"SELECT b.id {joins}{where} "
            f"ORDER BY b.title LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    ).all()
    ids = [row[0] for row in rows]

    books: list[Book] = []
    if ids:
        loaded = list(
            session.scalars(
                select(Book)
                .where(Book.id.in_(ids))
                .options(
                    selectinload(Book.author),
                    selectinload(Book.subjects),
                    selectinload(Book.series),
                    selectinload(Book.editions).selectinload(Edition.files),
                )
            ).all()
        )
        order = {book_id: index for index, book_id in enumerate(ids)}
        books = sorted(loaded, key=lambda book: order[book.id])

    return books, total, facets
