# Libarr

Self-hosted, *Arr-style eBook automation platform: monitor authors and genres,
search indexers, download, import, organize, and serve your library via OPDS
and a built-in reader.

> **Status: Phases 1–4 implemented (2026-08-22) — 295 tests passing.**
> The full *Arr loop is live: monitor → [scheduler] → RSS/search → decision →
> grab (5 download clients) → hardlink import → named library → OPDS, plus
> genre/keyword discovery, wanted/upgrade tracking, offline metadata via OL
> dumps, automatic monitoring cycles, requests, conversion, device sync, OIDC,
> PostgreSQL support, and a split worker. See `docs/RESUME.md` for the
> fresh-session handoff and `docs/implementation-plan.md` for the remaining
> operational hardening and ecosystem backlog.

## Layout

- `src/libarr/` — FastAPI application (modular monolith: metadata, indexers,
  download clients, acquisition, library serving, scheduler)
- `web/` — Vue 3 SPA
- `tests/` — pytest suite (295 tests)
- `docker/` — Dockerfile + compose (single `/data` volume, hardlink-safe)

## Development

```bash
uv sync                     # create venv + lockfile (Python 3.12)
uv run alembic upgrade head # migrate the database
uv run pytest               # run tests
uv run ruff check src tests migrations
uv run mypy src
uv run uvicorn libarr.main:app --reload --port 8787
# optional: cd web && npm run dev -- --port 5173   (SPA, proxies /api → 8787)
```

Requires [uv](https://docs.astral.sh/uv/). The app listens on port **8787**
(a nod to Readarr's old port — it's the natural successor).

Operational extras: `libarr metadata-import --dump ol_dump_works.txt` (offline
metadata mirror), `LIBARR_SCHEDULER_ENABLED=false` to disable background cycles,
`LIBARR_APPRISE_URLS` for notifications.

Portable catalog migration (credentials, users, and download-client secrets are
deliberately excluded):

```bash
libarr export --output libarr-metadata.zip
libarr import --input libarr-metadata.zip       # target catalog must be empty
libarr import --input libarr-metadata.zip --replace  # also clears transient catalog state
```

## Docker (production)

```bash
cd docker && docker compose up -d --build
```

Two containers sharing one `/data` volume (database + library + downloads on a
single filesystem so imports hardlink instead of copy):

- **libarr** — API + the built Vue SPA on `:8787` (migrations run on boot)
- **worker** — background jobs (`libarr worker --interval 300`): RSS sync,
  download watch, discovery lists, conversions

Set `PUID`/`PGID` to your host user ids in `docker-compose.yml` so the
container's files are yours. First run: open `http://localhost:8787` and the
app will prompt you to create the admin user. The supplied Compose file enables
`LIBARR_LAN_AUTH_BYPASS=true`: direct RFC1918, loopback, and IPv6 ULA clients
then act as the first admin without logging in. Disable it before putting Libarr
behind a reverse proxy, because the proxy's private peer address would be trusted.
