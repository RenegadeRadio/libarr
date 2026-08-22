# Libarr — Session Resume

Handoff for a fresh session. Everything needed to understand, run, verify, and
continue the project. Authoritative plan: `docs/implementation-plan.md`
(mirrors `~/.hermes/plans/2026-08-19_011209-libarr-ebook-platform.md`).

## Project state (2026-08-22)

**Phases 1–4 implemented, with 302 tests passing. The catalog can be migrated
between instances with `libarr export` / `libarr import`; credentials and users
are deliberately excluded from that portable archive.**

- **Phase 1 — "Libarr Lite"**: models + FTS5, filename parser, library scan, matcher,
  3-hop Open Library metadata (edition → work → author) with stale-while-error
  cache, enrichment, REST API, genre/keyword search with facets, OPDS 1.2,
  reader/progress/covers, forced auth (session cookie + API key + Basic for OPDS),
  Vue 3 frontend, Apprise notifications.
- **Phase 2 — the *Arr core**: Torznab/Newznab client; legal built-in indexers
  (**Gutenberg**, **Open Library/Internet Archive** — Standard Ebooks' OPDS is dead,
  401s, replaced); RSS sync; download clients (qBittorrent, Deluge, Transmission,
  SABnzbd, NZBGet) + grab/watch state machine; decision engine (quality profiles,
  comparer: format → custom → protocol → priority → seeds → age → size, junk filter);
  hardlink-first import pipeline (remote path mapping, OPF verify, naming templates,
  quarantine); wanted lists (missing/cutoff), search-now, history log, monitor
  toggles, upgrade loop; discovery lists (subject thesaurus, OL `subject:` search +
  Google Books fallback, saved import lists).
- **Phase 2.5 — resilience**: `libarr metadata-import --dump ol_dump_*.txt` →
  local mirror (`dump_rows` + `dump_isbns`); ISBN lookups resolve **fully offline**
  when Open Library is down (provider-down integration test).
- **Scheduler**: in-process cadence loop (interval ± jitter, per-cycle isolation)
  wired into the app lifespan — RSS/watch/discovery run automatically
  (`LIBARR_SCHEDULER_ENABLED/INTERVAL_SECONDS/JITTER_SECONDS`).

## Run it

```bash
cd ~/libarr
uv sync                                   # Python 3.12, uv-managed
uv run alembic upgrade head               # migrate (CLI metadata-import self-migrates)
uv run uvicorn libarr.main:app --port 8787   # API on :8787; scheduler starts with it
cd web && npm run dev -- --port 5173      # SPA dev server (proxies /api → 8787)
```

The dev DB (`data/libarr.db`) is already seeded: admin user
(**admin / hunter2!** — change in prod), 53 books (3 scanned + 50 fantasy works
imported via discovery), 7 dump rows + 3 ISBNs, one Gutenberg indexer, one
queued item ("Pride and Prejudice", queued autonomously by the scheduler).
`scripts/seed_demo.py` recreates the demo library from scratch.

## Verify

```bash
uv run pytest -q          # 302 tests
uv run ruff check src tests migrations && uv run ruff format --check src tests migrations
uv run mypy src
```

UI smoke (needs backend :8787 + vite :5173 up, admin seeded):
```bash
node scripts/ui-smoke.mjs          # login → library grid → genre search (Phase 1)
# discovery flow script lives at /tmp/ui_discovery.mjs (not committed)
```

API smoke with curl:
```bash
curl -c /tmp/jar -X POST localhost:8787/api/v1/auth/login \
  -H 'Content-Type: application/json' -d '{"username":"admin","password":"hunter2!"}'
curl -b /tmp/jar localhost:8787/api/v1/health
```

## Architecture map (src/libarr/)

| Module | Purpose |
|---|---|
| `models/`, `db.py`, `fts.py` | ORM (16 tables, migrations 0001–0010), SQLite WAL, FTS5 |
| `metadata/` | providers (openlibrary, googlebooks), cache (stale-while-error), enrich, matcher, normalize, subjects (thesaurus), dumps (offline mirror) |
| `indexers/` | base (Release/Candidate protocol), torznab, gutenberg, openlibrary, registry |
| `clients/` | base (ClientItem), qbittorrent, deluge, transmission, sabnzbd, nzbget, registry |
| `acquisition/` | parser, wanted (match/upgrade), quality, decision, candidates, import_pipeline, epub_meta |
| `tasks/` | rss, download_watch, search (search-now) |
| `api/` | routes (all /api/v1 endpoints + /opds at root), auth, schemas, serializers |
| `scheduler.py`, `discovery.py`, `history.py`, `notify.py`, `cli.py` | glue |

## API surface (all under /api/v1, auth required except /auth/*)

books, authors (+ PATCH monitor), search (FTS + genre facets), covers, progress,
indexers (CRUD + /test), clients (CRUD + /test), queue triggers
(`/system/rss-sync`, `/system/process-queue`, `/system/discovery-lists`),
wanted/missing, wanted/cutoff, history, discovery, discovery-lists.
OPDS 1.2 catalog at `/opds` (Basic auth). First run: POST /auth/bootstrap creates admin.

## What's next

Provider health/status reporting and provider failure drills are the main
operational hardening items. Ecosystem gaps are external import lists
(Goodreads/StoryGraph/Open Library), per-user request limits, and RAR extraction.
Smaller follow-ups: batch-search politeness, scheduler task locking for
multi-instance deployments, frontend controls for path mappings and naming
templates, PostgreSQL full-text parity, and a real frontend test suite.

## This-machine quirks (Arch/Hyprland)

- Background shells lack PATH (`uv` at `~/.hermes/bin`) and Wayland/X11 env
  (`WAYLAND_DISPLAY=wayland-1 DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000`) —
  export before launching GUI apps.
- `browser_exec` blocks private/localhost URLs; cua-driver can't see
  Wayland-native windows (Firefox must use XWayland; even then XAUTHORITY is
  missing — prefer headless Chromium over CDP: see `scripts/ui-smoke.mjs`).
- Chromium hangs same-origin fetches on `401 + WWW-Authenticate` — require_user
  deliberately sends no WWW-Authenticate header (regression test exists).
- respx mocks need `@respx.mock` decorators; OL throttles rapid bursts
  (graceful degradation is by design).
