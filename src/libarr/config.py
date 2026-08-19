"""Application configuration via pydantic-settings (env prefix LIBARR_)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every field overridable with LIBARR_<FIELD> env var."""

    model_config = SettingsConfigDict(env_prefix="LIBARR_", env_file=".env")

    # Data layout — in Docker all three live under the single /data volume.
    data_dir: Path = Path("data")
    library_root: Path = Path("data/books")
    download_dir: Path = Path("data/downloads")
    database_url: str = "sqlite:///data/libarr.db"

    # Background services
    redis_url: str = "redis://localhost:6379"
    rss_interval_minutes: int = 60

    # Security
    auth_enabled: bool = True
    # Session signing secret. Unset → ephemeral random per start (cookies
    # invalidate on restart). Set LIBARR_SECRET_KEY for persistence.
    secret_key: str | None = None
