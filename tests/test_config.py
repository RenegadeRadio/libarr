"""Phase 0.5 — pydantic-settings configuration with env overrides."""

from pathlib import Path

from libarr.config import Settings


def test_defaults():
    s = Settings()
    assert s.rss_interval_minutes == 60
    assert s.auth_enabled is True
    assert s.lan_auth_bypass is False
    assert isinstance(s.library_root, Path)


def test_env_override(monkeypatch):
    monkeypatch.setenv("LIBARR_RSS_INTERVAL_MINUTES", "5")
    monkeypatch.setenv("LIBARR_AUTH_ENABLED", "false")
    monkeypatch.setenv("LIBARR_LAN_AUTH_BYPASS", "true")
    s = Settings()
    assert s.rss_interval_minutes == 5
    assert s.auth_enabled is False
    assert s.lan_auth_bypass is True


def test_data_paths_defaults():
    s = Settings()
    assert s.database_url == "sqlite:///data/libarr.db"
    assert s.library_root == Path("data/books")
    assert s.download_dir == Path("data/downloads")
