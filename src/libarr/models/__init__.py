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
    monitored: Mapped[bool] = mapped_column(default=False)
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


class DownloadClientRow(Base):
    """A configured download client (plan 2.2): qBittorrent/Deluge/Transmission/SABnzbd/NZBGet."""

    __tablename__ = "download_clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    url: Mapped[str | None] = mapped_column(String(512))
    username: Mapped[str | None] = mapped_column(String(128))
    password: Mapped[str | None] = mapped_column(String(255))
    api_key: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(default=True)
    priority: Mapped[int] = mapped_column(default=100)
    # Remote Path Mapping: paths as the client sees them → paths on the
    # library host (used by the import pipeline to find completed files).
    remote_path: Mapped[str | None] = mapped_column(String(512))
    local_path: Mapped[str | None] = mapped_column(String(512))
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
    client_name: Mapped[str | None] = mapped_column(String(64))
    client_download_id: Mapped[str | None] = mapped_column(String(255))
    manual: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    error: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )


class HistoryEvent(Base):
    """Pipeline event log (plan 2.5): grab / import / upgrade / fail / discovery."""

    __tablename__ = "history_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id"))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    details: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class DiscoveryList(Base):
    """A saved discovery/import list query (plan 2.6.4), evaluated on schedule."""

    __tablename__ = "discovery_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    query: Mapped[str] = mapped_column(
        String(1024), nullable=False
    )  # JSON: q/genre/year_min/year_max/language
    schedule_days: Mapped[int] = mapped_column(default=7)
    max_per_run: Mapped[int] = mapped_column(default=10)
    auto_monitor: Mapped[bool] = mapped_column(default=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class DumpRow(Base):
    """One Open Library dump record (plan 2.5) — the offline metadata mirror."""

    __tablename__ = "dump_rows"

    ol_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # work|edition|author
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class DumpIsbn(Base):
    """Edition-dump ISBN index: isbn13 → edition/work keys (offline lookup)."""

    __tablename__ = "dump_isbns"

    isbn13: Mapped[str] = mapped_column(String(32), primary_key=True)
    edition_key: Mapped[str] = mapped_column(String(128), nullable=False)
    work_key: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(512), nullable=False)


class ConversionJob(Base):
    """A queued `ebook-convert` subprocess job (Phase 3 conversion worker)."""

    __tablename__ = "conversion_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id"), nullable=False)
    target_format: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="queued", nullable=False
    )  # queued|working|done|failed
    output_path: Mapped[str | None] = mapped_column(String(1024))
    error: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )


class KoreaderProgress(Base):
    """Per-user reading progress synced from KOReader devices (Phase 3)."""

    __tablename__ = "koreader_progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    document: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512))
    progress: Mapped[float] = mapped_column(default=0.0, nullable=False)
    device: Mapped[str | None] = mapped_column(String(64))
    client: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )

    __table_args__ = (UniqueConstraint("user_id", "document", name="uq_koreader_user_doc"),)


class Shelf(Base):
    """A per-user book collection (Phase 4)."""

    __tablename__ = "shelves"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    books: Mapped[list["Book"]] = relationship(secondary="shelf_books", lazy="selectin")


class ShelfBook(Base):
    __tablename__ = "shelf_books"

    shelf_id: Mapped[int] = mapped_column(ForeignKey("shelves.id"), primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), primary_key=True)


class User(Base):
    """Application user (plan Task 1.11). Admin bootstraps on first run."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    notify_events: Mapped[str] = mapped_column(
        String(512), default='["import","search"]', nullable=False
    )
    oidc_sub: Mapped[str | None] = mapped_column(String(128), unique=True)
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
    "ConversionJob",
    "DiscoveryList",
    "DownloadClientRow",
    "DumpIsbn",
    "DumpRow",
    "Edition",
    "File",
    "HistoryEvent",
    "Indexer",
    "KoreaderProgress",
    "MetadataCache",
    "QueueItem",
    "ReadingProgress",
    "Series",
    "Setting",
    "Shelf",
    "ShelfBook",
    "Subject",
    "User",
]
