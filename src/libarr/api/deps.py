"""FastAPI dependencies: request-scoped DB sessions bound to the app engine."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from libarr.config import Settings
from libarr.db import make_engine, session_factory

_engine: Engine | None = None


def get_engine() -> Engine:
    """Lazily build the app engine from settings (creates the sqlite parent dir)."""
    global _engine
    if _engine is None:
        settings = Settings()
        if settings.database_url.startswith("sqlite"):
            db_path = settings.database_url.removeprefix("sqlite:///")
            if not db_path.startswith(":memory:"):
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _engine = make_engine(settings.database_url)
    return _engine


def get_session() -> Iterator[Session]:
    """Request-scoped session (overridden in tests with a migrated tmp db)."""
    with session_factory(get_engine())() as session:
        yield session
