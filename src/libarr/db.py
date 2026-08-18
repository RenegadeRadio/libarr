"""SQLAlchemy engine/session setup with SQLite WAL mode."""

from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all Libarr ORM models."""


def make_engine(url: str) -> Engine:
    """Create an engine. SQLite gets WAL mode + FK enforcement via connect events."""
    kwargs: dict[str, Any] = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _set_sqlite_pragma)
    return engine


def _set_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
    """Enable WAL journaling and foreign keys per SQLite connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def session_factory(engine: Engine) -> sessionmaker:
    """Build a sessionmaker bound to the given engine."""
    return sessionmaker(bind=engine, expire_on_commit=False)
