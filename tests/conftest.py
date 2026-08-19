"""Shared pytest fixtures: alembic-migrated tmp sqlite engine + session."""

from pathlib import Path

import alembic.command
import alembic.config
import pytest
from fastapi.testclient import TestClient

from libarr.api.deps import get_session
from libarr.db import make_engine, session_factory
from libarr.main import app

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _no_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the in-process scheduler out of tests that boot the app."""
    monkeypatch.setenv("LIBARR_SCHEDULER_ENABLED", "false")


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


@pytest.fixture()
def raw_client(db):
    """TestClient with the DB session overridden, but NOT authenticated."""

    def override():
        with session_factory(db)() as s:
            yield s

    app.dependency_overrides[get_session] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def client(raw_client, db):
    """Authenticated TestClient: bootstraps an admin and logs in."""
    raw_client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": "hunter2!"},
    )
    raw_client.post("/api/v1/auth/login", json={"username": "admin", "password": "hunter2!"})
    yield raw_client, db
