# Libarr

Self-hosted, *Arr-style eBook automation platform: monitor authors and genres,
search indexers, download, import, organize, and serve your library via OPDS
and a built-in reader.

> **Status: Phases 1, 2 & 2.5 complete (2026-08-19) — 214 tests passing.**
> The full *Arr loop is live: monitor → [scheduler] → RSS/search → decision →
> grab (5 download clients) → hardlink import → named library → OPDS, plus
> genre/keyword discovery, wanted/upgrade tracking, offline metadata via OL
> dumps, and automatic monitoring cycles. Live-verified end-to-end in a real
> browser and in a zero-touch autonomous grab. **Next: Phase 3 — ecosystem**
> (request UI, import lists, conversion, device sync). See `docs/RESUME.md`
> for the fresh-session handoff and `docs/implementation-plan.md` for the plan.

## Layout

- `src/libarr/` — FastAPI application (modular monolith: metadata, indexers,
  download clients, acquisition, library serving, scheduler)
- `web/` — Vue 3 SPA
- `tests/` — pytest suite (214 tests)
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
