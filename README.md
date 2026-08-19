# Libarr

Self-hosted, *Arr-style eBook automation platform: monitor authors and genres,
search indexers, download, import, organize, and serve your library via OPDS
and a built-in reader.

> **Status: Phase 1 complete (2026-08-19) — "Libarr Lite".** Library scan → metadata
> enrichment → genre/keyword search → OPDS catalog → reader/covers → auth → Vue 3
> frontend, all live-verified; **91 tests passing**, headless-browser UI smoke test
> included. Next: Phase 2 — the *Arr core (indexers, download clients, decision
> engine, import pipeline, RSS monitoring). See `docs/implementation-plan.md`.

## Layout

- `src/libarr/` — FastAPI application (modular monolith: metadata, indexers,
  download clients, acquisition, library serving)
- `web/` — Vue 3 SPA (Phase 0.8)
- `tests/` — pytest suite
- `docker/` — Dockerfile + compose (single `/data` volume, hardlink-safe)

## Development

```bash
uv sync                     # create venv + lockfile (Python 3.12)
uv run pytest               # run tests
uv run ruff check src tests
uv run mypy src
uv run uvicorn libarr.main:app --reload --port 8787
```

Requires [uv](https://docs.astral.sh/uv/). The app listens on port **8787**
(a nod to Readarr's old port — it's the natural successor).
