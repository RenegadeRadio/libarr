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

    # Notifications (Apprise): comma-separated service URLs, e.g.
    # "tgram://bottoken/chatid, ntfy://topic". Empty = notifications off.
    apprise_urls: str = ""

    # Import pipeline (plan 2.4)
    library_dir: str = "data/books"
    import_template: str = (
        "{Author Name}/{Series} - {Book Title} ({Release Year})/"
        "{Series} - {Book Title} ({Release Year}) - {Author}.{Extension}"
    )
    import_mode: str = "hardlink"  # hardlink | copy | move

    # Background scheduler (plan scheduler.py): runs RSS sync, the download
    # watch and discovery lists on cadence. Disable for single-shot use.
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 300
    scheduler_jitter_seconds: int = 60
