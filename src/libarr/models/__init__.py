"""ORM models. Importing this package registers all tables on Base.metadata.

Schema mirrors plan §4.2: authors → books → editions → files, with series,
subjects (genre facets) and a contentless FTS5 search index (book_fts).
"""

from datetime import UTC, date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from libarr.db import Base


def _now() -> datetime:
    # Naive UTC: SQLite returns naive datetimes; keep everything consistent.
    return datetime.now(UTC).replace(tzinfo=None)


class Author(Base):
    __tablename__ = "authors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_name: Mapped[str | None] = mapped_column(String(255))
    slug: Mapped[str | None] = mapped_column(String(255))
    biography: Mapped[str | None] = mapped_column(Text)
    ol_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    cover_path: Mapped[str | None] = mapped_column(String(1024))
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )

    books: Mapped[list["Book"]] = relationship(back_populates="author")


class Series(Base):
    __tablename__ = "series"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("authors.id"))
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("authors.id"))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(512))
    series_id: Mapped[int | None] = mapped_column(ForeignKey("series.id"))
    series_position: Mapped[int | None] = mapped_column()
    work_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    language: Mapped[str | None] = mapped_column(String(8))
    description: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column()
    year: Mapped[int | None] = mapped_column()
    cover_path: Mapped[str | None] = mapped_column(String(1024))
    monitored: Mapped[bool] = mapped_column(default=False, nullable=False)
    path: Mapped[str | None] = mapped_column(String(1024))
    metadata_json: Mapped[str | None] = mapped_column(Text)
    date_added: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )

    author: Mapped[Author | None] = relationship(back_populates="books")
    series: Mapped[Series | None] = relationship()
    editions: Mapped[list["Edition"]] = relationship(back_populates="book")
    subjects: Mapped[list["Subject"]] = relationship(back_populates="book")


class Edition(Base):
    __tablename__ = "editions"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    isbn13: Mapped[str | None] = mapped_column(String(13), unique=True)
    isbn10: Mapped[str | None] = mapped_column(String(10))
    publisher: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[date | None] = mapped_column(Date)
    format: Mapped[str | None] = mapped_column(String(32))
    page_count: Mapped[int | None] = mapped_column()
    ol_edition_key: Mapped[str | None] = mapped_column(String(64))
    google_volume_id: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[str | None] = mapped_column(Text)

    book: Mapped[Book] = relationship(back_populates="editions")
    files: Mapped[list["File"]] = relationship(back_populates="edition")


class File(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(primary_key=True)
    edition_id: Mapped[int | None] = mapped_column(ForeignKey("editions.id"))
    path: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    date_added: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    date_scanned: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    edition: Mapped[Edition | None] = relationship(back_populates="files")


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (UniqueConstraint("book_id", "slug", name="uq_subject_book_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    # openlibrary | googlebooks | user | calibre
    source: Mapped[str] = mapped_column(String(32), nullable=False)

    book: Mapped[Book] = relationship(back_populates="subjects")


class Setting(Base):
    """Key/value application settings."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(String(4096), nullable=False)


class Indexer(Base):
    """An indexer of ebook releases (plan 2.1): Torznab/Newznab or built-in."""

    __tablename__ = "indexers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # ^ torznab | gutenberg | standardebooks
    url: Mapped[str | None] = mapped_column(String(512))
    api_key: Mapped[str | None] = mapped_column(String(255))
    categories: Mapped[str] = mapped_column(String(255), default="7000,7010,7030,7050")
    priority: Mapped[int] = mapped_column(default=100)
    enabled: Mapped[bool] = mapped_column(default=True)
    rss_enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class QueueItem(Base):
    """A grabbed release awaiting download/import (plan 2.1.3).

    status: queued → downloading → importing → imported | failed
    """

    __tablename__ = "queue_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    release_guid: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    indexer_name: Mapped[str] = mapped_column(String(64), nullable=False)
    download_url: Mapped[str | None] = mapped_column(String(1024))
    format: Mapped[str | None] = mapped_column(String(16))
    size_bytes: Mapped[int | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    error: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )


class User(Base):
    """Application user (plan Task 1.11). Admin bootstraps on first run."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class ReadingProgress(Base):
    """Per-profile reading position for a book (plan Task 1.9).

    Keyed by (book_id, profile): 'profile' is a client-supplied device/user
    name until multi-user auth lands (Phase 4).
    """

    __tablename__ = "reading_progress"

    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), primary_key=True)
    profile: Mapped[str] = mapped_column(String(64), primary_key=True)
    position: Mapped[float] = mapped_column(nullable=False)  # 0.0–1.0
    location: Mapped[str | None] = mapped_column(String(512))  # e.g. epubcfi(...)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )


class MetadataCache(Base):
    """Local cache of provider responses — the anti-Readarr resilience layer.

    Every external metadata response is stored here (plan §2.3): fresh within
    TTL, stale-while-error when the provider is down, and dump-importable so
    the app keeps working with zero internet access.
    """

    __tablename__ = "metadata_cache"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    etag: Mapped[str | None] = mapped_column(String(128))


__all__ = [
    "Author",
    "Book",
    "Edition",
    "File",
    "Indexer",
    "MetadataCache",
    "QueueItem",
    "ReadingProgress",
    "Series",
    "Setting",
    "Subject",
    "User",
]
