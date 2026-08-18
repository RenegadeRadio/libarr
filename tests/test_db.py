"""Phase 0.4 — SQLAlchemy engine, WAL pragma, alembic migrations, settings round-trip."""

from pathlib import Path

import alembic.command
import alembic.config
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from libarr.db import make_engine, session_factory
from libarr.models import Setting

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def migrated_db(tmp_path):
    """Engine whose schema is created by applying alembic migrations to a tmp sqlite file."""
    url = f"sqlite:///{tmp_path / 'test.db'}"
    cfg = alembic.config.Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    alembic.command.upgrade(cfg, "head")

    engine = make_engine(url)
    yield engine
    engine.dispose()


def test_alembic_upgrade_creates_settings_table(migrated_db):
    with session_factory(migrated_db)() as session:
        session.add(Setting(key="rss_interval", value="60"))
        session.commit()

        row = session.scalars(select(Setting)).one()
        assert row.key == "rss_interval"
        assert row.value == "60"


def test_setting_key_is_unique(migrated_db):
    with session_factory(migrated_db)() as session:
        session.add_all(
            [Setting(key="theme", value="dark"), Setting(key="theme", value="light")]
        )
        with pytest.raises(IntegrityError):
            session.commit()
