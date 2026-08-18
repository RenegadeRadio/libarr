# Libarr

Self-hosted, *Arr-style eBook automation platform: monitor authors and genres,
search indexers, download, import, organize, and serve your library via OPDS
and a built-in reader.

> **Status: Phase 0 (scaffold) — not functional yet.** See
> `.hermes/plans/2026-08-19_011209-libarr-ebook-platform.md` for the full
> implementation plan.

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
