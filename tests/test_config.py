"""Phase 0.5 — pydantic-settings configuration with env overrides."""

from pathlib import Path

from libarr.config import Settings


def test_defaults():
    s = Settings()
    assert s.rss_interval_minutes == 60
    assert s.auth_enabled is True
    assert isinstance(s.library_root, Path)


def test_env_override(monkeypatch):
    monkeypatch.setenv("LIBARR_RSS_INTERVAL_MINUTES", "5")
    monkeypatch.setenv("LIBARR_AUTH_ENABLED", "false")
    s = Settings()
    assert s.rss_interval_minutes == 5
    assert s.auth_enabled is False


def test_data_paths_defaults():
    s = Settings()
    assert s.database_url == "sqlite:///data/libarr.db"
    assert s.library_root == Path("data/books")
    assert s.download_dir == Path("data/downloads")
