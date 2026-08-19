"""ORM → dict serializers (kept dumb so routes stay thin and testable)."""

from __future__ import annotations

from typing import Any

from libarr.models import Author, Book, DownloadClientRow, Indexer


def serialize_author(author: Author) -> dict[str, Any]:
    return {
        "id": author.id,
        "name": author.name,
        "book_count": len(author.books),
    }


def serialize_author_detail(author: Author) -> dict[str, Any]:
    return {
        "id": author.id,
        "name": author.name,
        "sort_name": author.sort_name,
        "biography": author.biography,
        "ol_key": author.ol_key,
        "book_count": len(author.books),
    }


def serialize_book(book: Book) -> dict[str, Any]:
    return {
        "id": book.id,
        "title": book.title,
        "subtitle": book.subtitle,
        "author_name": book.author.name if book.author else None,
        "year": book.year,
        "language": book.language,
        "monitored": book.monitored,
        "cover_path": book.cover_path,
        "series_title": book.series.title if book.series else None,
        "series_position": book.series_position,
        "subjects": sorted(s.name for s in book.subjects),
        "formats": sorted({e.format for e in book.editions if e.format}),
    }


def serialize_book_detail(book: Book) -> dict[str, Any]:
    data = serialize_book(book)
    data.update(
        {
            "description": book.description,
            "work_key": book.work_key,
            "page_count": book.page_count,
            "editions": [
                {
                    "id": edition.id,
                    "isbn13": edition.isbn13,
                    "isbn10": edition.isbn10,
                    "publisher": edition.publisher,
                    "published_at": edition.published_at,
                    "format": edition.format,
                    "files": [
                        {
                            "id": f.id,
                            "path": f.path,
                            "format": f.format,
                            "size_bytes": f.size_bytes,
                        }
                        for f in edition.files
                    ],
                }
                for edition in book.editions
            ],
        }
    )
    return data


def serialize_indexer(row: Indexer) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "kind": row.kind,
        "url": row.url,
        "api_key": row.api_key,
        "categories": row.categories,
        "priority": row.priority,
        "enabled": row.enabled,
        "rss_enabled": row.rss_enabled,
        "created_at": row.created_at,
    }


def serialize_client(row: DownloadClientRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "kind": row.kind,
        "url": row.url,
        "username": row.username,
        "password": row.password,
        "api_key": row.api_key,
        "enabled": row.enabled,
        "priority": row.priority,
        "remote_path": row.remote_path,
        "local_path": row.local_path,
        "created_at": row.created_at,
    }
