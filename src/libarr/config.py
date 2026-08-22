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
    # Trust direct RFC1918/loopback/IPv6-ULA clients as the first admin user.
    # Keep off when Libarr sits behind a reverse proxy: the proxy peer itself
    # may have a private address even when the original visitor does not.
    lan_auth_bypass: bool = False
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

    # Conversion worker (Phase 3): ebook-convert output directory.
    conversion_out_dir: str = "data/converted"

    # Send-to-Kindle (Phase 3): SMTP settings for the email bridge.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    # OIDC single sign-on (Phase 4): discovery issuer + client credentials.
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""

    # Chat assistant (Phase 4.5): optional OpenAI-compatible model for intent
    # extraction; without a key the heuristic parser + themes KB are used.
    chat_api_key: str = ""
    chat_base_url: str = "https://api.openai.com/v1"
    chat_model: str = "gpt-4o-mini"
    goodreads_ratings_enabled: bool = False
