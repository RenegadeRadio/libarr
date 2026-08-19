"""Phase 0.4 — SQLAlchemy engine, WAL pragma, alembic migrations, settings round-trip."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from libarr.db import session_factory
from libarr.models import Setting


def test_alembic_upgrade_creates_settings_table(db):
    with session_factory(db)() as session:
        session.add(Setting(key="rss_interval", value="60"))
        session.commit()

        row = session.scalars(select(Setting)).one()
        assert row.key == "rss_interval"
        assert row.value == "60"


def test_setting_key_is_unique(db):
    with session_factory(db)() as session:
        session.add_all([Setting(key="theme", value="dark"), Setting(key="theme", value="light")])
        with pytest.raises(IntegrityError):
            session.commit()
