"""Shared pytest fixtures: alembic-migrated tmp sqlite engine + session."""

from pathlib import Path

import alembic.command
import alembic.config
import pytest

from libarr.db import make_engine, session_factory

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def db(tmp_path):
    """Engine whose schema is created by applying alembic migrations to a tmp sqlite file."""
    url = f"sqlite:///{tmp_path / 'test.db'}"
    cfg = alembic.config.Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    alembic.command.upgrade(cfg, "head")

    engine = make_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(db):
    """Session scoped to the migrated engine."""
    with session_factory(db)() as s:
        yield s
