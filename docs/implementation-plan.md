# Libarr — An *Arr-Style eBook Automation Platform — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a self-hosted, *Arr-style eBook platform that automates the full lifecycle of a personal/community ebook library — metadata enrichment, author/edition monitoring, indexer search, download-client integration, import/rename, quality-based upgrades, OPDS/reader delivery — with a metadata layer designed to *never* die the way Readarr's did.

**Architecture:** A modular monolith ("the stack in one process, separable later") with six bounded modules mirroring the *Arr family: acquisition engine (Sonarr/Radarr), indexer manager (Prowlarr), metadata service (Readarr's BookInfo, rebuilt right), library server + OPDS (Calibre-Web), notification/queue plumbing, and a single SPA frontend (the "Overseerr-style" UI is Phase 3). SQLite-first, Docker-first, GPL-3.0, Python.

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2 · SQLite (optional Postgres) · ARQ/Redis for the async worker · ebooklib for EPUB parsing · aiohttp for provider/indexer HTTP · Apprise for notifications · Vue 3 + Vite SPA (or plain server-rendered HTMX for MVP, see Open Questions).

## Progress — 2026-08-19

**Phase 0 (scaffold): COMPLETE** — repo `github.com/RenegadeRadio/libarr` (public), CI green (ruff/mypy/pytest/docker), Docker image boots and serves `/api/v1/health`, Vue 3 SPA shell builds.

**Phase 1 (Libarr Lite): COMPLETE (2026-08-19).** All 13 tasks shipped: models+FTS5, parser, scan, matcher, providers (3-hop OL resolution) with stale-while-error cache, enrichment, REST API, genre/keyword search with facets, OPDS 1.2, reader/progress/covers, forced auth (cookie/API-key/Basic), Vue 3 frontend (login, grid, search UI), Apprise notifications. **91 tests passing** + headless-Chromium UI smoke test (`scripts/ui-smoke.mjs`). Live-verified end-to-end against real Open Library data.

**Phase 2.5 (metadata resilience): COMPLETE (2026-08-19).** OL dump ingestion → local mirror; ISBN lookups resolve fully offline when Open Library is down (anti-Readarr drill, tested with a provider-down integration test). **211 tests passing.** Plus: in-process scheduler (cadence ± jitter, per-cycle isolation) wired into the app lifespan — RSS/watch/discovery now run automatically (`LIBARR_SCHEDULER_*` config); live-verified autonomous grab (scheduler → Gutenberg → matched wanted book → queued, no human action).

**Phase 3 (ecosystem): COMPLETE (2026-08-19).** Request flow, conversion worker (ebook-convert + kepubify), archive unpacking, per-user notifications, calendar, Anna's Archive manual-link indexer, Send-to-Kindle, KOReader sync. **242 tests passing.**

**Phase 2 (the *Arr core): COMPLETE (2026-08-19).** All workstreams shipped: Torznab/Newznab + Gutenberg + Open Library/IA indexers, RSS sync, 5 download clients + grab/watch state machine, decision engine (quality profiles + comparer + candidate filtering), hardlink-first import pipeline with naming templates, wanted/history/monitoring/upgrade loop, discovery lists + subject thesaurus. **200 tests passing**; live-verified end-to-end in a real browser (discover 50 fantasy works → import → wanted). Next: **Phase 2.5 metadata resilience (OL dumps)** → Phase 3 ecosystem (request UI, conversion, Kobo/Kindle sync).

---
## 1. Executive Summary — Why Build This Now

**Readarr — the book app in the official *Arr family — was retired by the Servarr team on 2025-06-27.** The stated causes are a textbook case study in how media automation dies:

1. **Closed metadata backend.** Readarr's "BookInfo" metadata server was a *proprietary proxy over the Goodreads API*. Goodreads killed public API access → the proxy died → the app became unusable. The metadata server was not open source, so the community could not self-host a fix.
2. **The escape hatch stalled.** A community effort to migrate to Open Library (a free, open, dumpable source) never shipped; the mapping between Goodreads IDs and Open Library IDs is a large, unfinished exercise.
3. **No maintainers.** ~900 open issues, effectively zero active devs, and a codebase that is an aging fork of Sonarr (itself years behind).

Meanwhile the demand is *unmet and growing*:

- r/selfhosted threads ("Have we figured out an alternative to Readarr?", "Readarr is dying") recur weekly.
- Existing alternatives are all partial: **Calibre-Web-Automated** (6.1k★) is a *library manager with automation scripts*, not an acquisition engine; **LazyLibrarian** is unmaintained and brittle; **Chaptarr** is very new; **BookLore/Grimmory** are excellent *library servers* with metadata enrichment but no download automation at all; **Mylar3** is comics-only.
- Nobody is building the *acquisition core* (monitor authors → search indexers → grab → import → upgrade) with a **modern, resilient metadata layer**. That is the gap Libarr fills.

**The one lesson that shapes this entire plan: metadata is the product.** *Arr apps' real value is the quality of their metadata glue (match releases to library items, pick the best release, name files perfectly). Readarr died because its metadata glue rotted. Libarr's metadata service must be open, multi-provider, cached locally, and dump-importable.*

---

## 2. Research Findings

### 2.1 How the *Arr stack actually works (the pattern we clone)

```
                        ┌─────────────────────────────────────────────┐
                        │  USER REQUESTS (UI / API / import lists)    │
                        └──────────────────┬──────────────────────────┘
                                           ▼
        ┌────────────────────────  ACQUISITION ENGINE  ───────────────┐
        │  Monitor state (authors/books/editions, wanted, cutoff)     │
        │  RSS sync (10–120 min): pull recent releases from indexers  │
        │     → diff against wanted list → auto-grab                  │
        │  Manual/automatic search → candidates → Decision Engine     │
        │  Decision Engine: quality > custom-format score > protocol  │
        │     > seeds > age > size  →  best release wins              │
        │  Queue + download tracking: poll download client API by     │
        │     per-app category tag → detect completion                 │
        │  Import pipeline: locate file → parse/verify → match to     │
        │     library item → hardlink/atomic-move → rename → scan     │
        └───────────────┬───────────────────────┬─────────────────────┘
                        │                       │
              INDEXER LAYER (Prowlarr/        DOWNLOAD CLIENTS
              Jackett/NZBHydra2 via           (qBittorrent, Deluge,
              Torznab/Newznab APIs)           Transmission, SABnzbd,
                        │                       NZBGet)
                        ▼                       ▼
                 Usenet/torrent           /data/downloads/...
                 indexers                          │
                        └───────────────► IMPORT (hardlink-first) ◄───┘
                                                      │
                                                      ▼
                                           LIBRARY SERVER
                                    (Plex/Jellyfin/Calibre-Web)
                                    scan → serve → OPDS → devices
```

Key engineering facts from the research:

- **Sonarr's find-loop is RSS-driven, not search-driven**: it queries indexers for *newly posted* releases on an interval (10–120 min) and diffs against what's wanted; active search only happens on add, manual trigger, or "wanted/missing" sweeps. A library of any size needs only ~10–144 indexer queries/day. (wiki.servarr.com/sonarr/faq)
- **Release comparison order (Sonarr, 2024)**: Quality → Custom Format score → Protocol → Episode count → Episode number → Indexer priority → Seeds/Peers → Age → Size. *Quality trumps all*; custom formats (TRaSH-Guides style scoring) let users re-rank. For books we swap "episode" for edition-release affinity (see §5.4).
- **Download tracking is category-tagged polling**: each *Arr uses a unique category/label in the client (e.g. `sonarr`, `radarr`); it polls the client API for items in its category, watches for completion, then imports. No webhooks needed (though supported).
- **Hardlink-first import**: *Arr import uses hard links (or atomic moves) so torrent seeding is never broken; this *requires* downloads and library to be on the **same filesystem/volume** — the infamous `/data` single-volume Docker pattern. Remote Path Mapping exists for when paths differ across containers.
- **Forced authentication** since Sonarr v4 (no more unauthenticated LAN mode), API keys, per-*arr port convention (Sonarr 8989, Radarr 7878, Readarr 8787, Prowlarr 9696).
- **Quality profiles + cutoff**: each monitored item targets a profile (e.g. "EPUB-Only", "Any Format") with a *cutoff*; anything below cutoff is eligible for upgrade grabs when a better release appears. "Wanted" UI = Missing + Cutoff Unmet lists.
- **Indexer protocol**: Torznab (torrents) / Newznab (usenet) — a simple XML/JSON API with `?t=search&q=...&cat=...` and RSS `t=search&q=&tvmazeid=`-style queries. **This is the integration standard** — supporting it means Prowlarr, Jackett, and NZBHydra2 users can point us at their existing indexer setups, and our indexer-manager can later sync to other *Arr apps. Book categories: `7000` Books, `7010` Ebooks, `7030` Ebooks/Comics, `7050` AudioBooks (verify per indexer).
- **Ecosystem glue**: overseerr/jellyseerr (request UI), bazarr (subtitles), unpackerr (archive extraction), autobrr (IRC announce racing), recyclarr (TRaSH config sync), Notifiarr. All speak each other's REST APIs.

### 2.2 The book-specific ecosystem

| Layer | Incumbent | Notes |
|---|---|---|
| Library DB format | **Calibre** (`metadata.db` SQLite + folder-per-book) | The de-facto standard since 2006. `calibredb` CLI + `ebook-convert` are the Swiss army knife. CWA and Readarr both integrate here. |
| Library *servers* | Calibre-Web, **Calibre-Web-Automated** (6.1k★), BookLore, Grimmory, Kavita, Komga | Calibre-Web/CWA are full-featured but dated UX; BookLore (2025) is the modern design benchmark: smart shelves, auto-metadata (Google Books/Open Library/Amazon), built-in reader, **BookDrop** watched-folder import, OPDS, Kobo/KOReader sync, OIDC. |
| Acquisition | Readarr (retired), LazyLibrarian (stale), Chaptarr (new), Mylar3 (comics) | Nobody has a healthy, modern, metadata-resilient acquisition engine. |
| Reading formats | EPUB (standard), MOBI/AZW3/KFX (Kindle), PDF, FB2, CBZ/CBR (comics), M4B/MP3 (audiobooks), KEPUB (Kobo) | Format preference is the book-world equivalent of video quality. Conversion via Calibre's `ebook-convert` (subprocess — avoids GPL contamination; see §10). |
| Delivery | **OPDS 1.2 (Atom) / 2.0 (JSON)** catalogs; Calibre wireless device protocol; KOReader OPDS; Kobo `kepubify`; Send-to-Kindle email | Every modern e-ink reader and reading app (KOReader, Kobo, PocketBook, iOS/Android readers) consumes OPDS. This is our "Plex app" — OPDS + a built-in web reader is table stakes. |
| Metadata sources | **Open Library** (free, ~40–50M works, monthly dumps, covers API), **Google Books** (free w/ key, ~40M), **ISBNdb** (paid $10–300/mo, 90M+), WorldCat, Amazon PAAPI, BookBrainz (community, MusicBrainz-for-books) | ISBN is the universal join key between providers. Readarr's death proves single-provider, closed, no-cache designs are fatal. |
| Indexers for books | Private trackers (MAM et al.), Usenet, LibGen/Anna's Archive mirrors, **legal sources: Project Gutenberg, Standard Ebooks, Open Library, publisher direct** | The platform must ship legal-by-default sources and be *agnostic* about what users add — same posture as every *Arr app. |

### 2.3 Lessons from Readarr's death (design constraints)

1. **Never depend on a single, closed metadata endpoint.** Multi-provider adapters with priority + fallback; every response cached locally forever; graceful degradation to cached/ISBN data.
2. **Metadata must be self-hostable.** Ship an optional `metadata-dump` subcommand that ingests Open Library data dumps into a local mirror (the santarrsgrotto/readarr-server pattern, made first-class). Readarr's community literally built this *after* the app died; we ship it as a supported feature.
3. **ID migration is a first-class concern.** ISBN (and normalized title/author/date) as the canonical join key from day one, so provider IDs (OL work key, Google volume ID, ISBNdb ID) are *aliases on the same row*, never the primary identity. This is what Readarr lacked (Goodreads-ID-as-identity).
4. **Large-author performance**: Readarr couldn't even load Stephen King because Goodreads paging broke. Our metadata fetches must be batchable, paginated, and lazy (fetch series/authors on demand, not eagerly).

---

## 3. Product Definition

**Persona:** self-hoster with an existing Calibre/Calibre-Web or bare-folder library, running Docker on a NAS/seedbox/VPS; wants "add an author, forget about it" behavior; reads on Kobo/Kindle/KOReader or in the browser.

### 3.1 MVP scope (Phase 1 — "Libarr Lite")
- Point at a library folder (bare files or existing Calibre structure) → scan, parse, extract metadata from EPUB OPF (`ebooklib`), enrich from metadata providers.
- Author/book/series/edition browse UI; covers; **genre & keyword search** (FTS5 full-text over titles/authors/descriptions/subjects + genre facets).
- Built-in web reader (EPUB/PDF) + **OPDS 1.2/2.0** so real e-readers can browse & download.
- "Monitor author/book" with legal-by-default sources wired (Gutenberg/Standard Ebooks/Open Library direct download) — *acquisition works end-to-end for legal sources on day one*.

### 3.2 v1 scope (Phase 2 — the *Arr core)
- Torznab/Newznab indexers (works with Prowlarr/Jackett/NZHydra2; own indexer-manager UI).
- Download clients: qBittorrent, Deluge, Transmission, SABnzbd, NZBGet — category-tagged, polled.
- Search → decision engine → grab → queue → import pipeline (hardlink-first, remote path mapping).
- Quality profiles + custom formats + cutoff upgrades; Wanted (Missing / Cutoff Unmet) UI; history.
- RSS monitoring loop for monitored authors.
- Notifications (Apprise), forced auth, API key, backup/restore, Docker images + compose.

### 3.2b Phase 3 — polish & ecosystem
- Request UI (Overseerr-style) for other users; import lists (Goodreads/StoryGraph/Open Library shelf sync); notifications per-book; calendar of upcoming releases; conversion worker (Calibre `ebook-convert`); Kobo KEPUB + Send-to-Kindle; KOReader progress sync; unpackerr-equivalent archive handling; audiobooks + comics as first-class media types.

### 3.3 Phase 4 — scale & compat
- Calibre `metadata.db` read/write compatibility mode (adopt folder-per-book layout, keep DB in sync); multi-user with OIDC; Postgres backend; plugin system; optional split into separate processes (true "stack" deployment); search over full text (SQLite FTS5).

### 3.4 Explicitly out of scope (v1)
- DRM removal/cracking tooling (out of scope by policy); storefront/payment; native mobile apps (OPDS covers it); video/music (that's Sonarr/Lidarr's job).

---

## 4. System Architecture

### 4.1 Service layout (modular monolith, run as one process by default)

```
libarr/
├── libarr/                      # Python package (single FastAPI app)
│   ├── main.py                  # app factory, lifespan, scheduler start
│   ├── config.py                # pydantic-settings; config.yaml + env
│   ├── db.py                    # SQLAlchemy engine/session, migrations (alembic)
│   ├── models/                  # ORM models (see §4.2)
│   ├── api/                     # REST routers: authors, books, search, activity,
│   │   │                        #   settings, system, auth
│   ├── metadata/                # MODULE: the resilience layer
│   │   ├── providers/           # openlibrary.py, googlebooks.py, isbndb.py, gutenberg.py,
│   │   │                        #   standardebooks.py — one adapter class each
│   │   ├── normalize.py         # provider payload → canonical Book/Edition/Author
│   │   ├── cache.py             # metadata_cache table + TTL + backoff
│   │   ├── matcher.py           # ISBN/title/author/date → canonical record joins
│   │   └── dumps.py             # OpenLibrary dump ingest (optional local mirror)
│   ├── indexers/                # MODULE: Torznab/Newznab client, category map,
│   │   │                        #   indexer CRUD, RSS sync task
│   ├── downloadclients/         # MODULE: qbittorrent.py, deluge.py, transmission.py,
│   │   │                        #   sabnzbd.py, nzbget.py — one adapter each
│   ├── acquisition/             # MODULE: the *Arr core
│   │   ├── decision.py          # release comparer (quality → cf → protocol → …)
│   │   ├── parser.py            # release-title filename parser (book flavored)
│   │   ├── queue.py             # grab queue + download tracking
│   │   ├── import_pipeline.py   # locate → parse → verify → match → hardlink → rename
│   │   ├── library_scan.py      # folder scan / calibre db ingest / BookDrop watch
│   │   └── naming.py            # author/book file + folder naming templates
│   ├── library/                 # MODULE: serving
│   │   ├── opds.py              # OPDS 1.2 (Atom) + 2.0 (JSON) catalogs
│   │   ├── reader.py            # EPUB/PDF streaming + reading-progress API
│   │   └── covers.py            # cover extraction (EPUB) + proxy caching
│   ├── notify.py                # Apprise wrapper
│   ├── tasks.py                 # ARQ worker: rss_sync, search, import, upgrade, scan
│   └── scheduler.py             # cadence loop (interval ± jitter, isolation) — wired into lifespan; ARQ/Redis swappable later
├── web/                         # Vue 3 + Vite SPA (or HTMX MVP, see Q3)
├── docker/                      # Dockerfile, docker-compose.yml, entrypoint
├── tests/                       # see §8
└── pyproject.toml
```

**Rationale for modular monolith:** the *Arr stack's actual deployment reality is *several* apps talking over HTTP. A monolith with module boundaries delivers the same capabilities with one deployable, one DB, no inter-service auth — while keeping the seams (each module has a clean internal interface) so a later split into `libarr-core` / `libarr-metadata` / `libarr-indexers` processes is mechanical. CWA proves the all-in-one shape is what users actually run.

### 4.2 Data model (SQLite, WAL mode)

```
authors(id PK, name, sort_name, slug, biography, ol_key, goodreads_key?, cover_path,
        created_at, updated_at)
books(id PK, author_id FK, title, subtitle, series_id FK?, series_position, work_key UNIQ,
      language, description, page_count, year, cover_path, monitored BOOL,
      quality_profile_id FK, path, date_added, metadata_json)        # metadata_json = last-known provider payload
series(id PK, title, author_id FK, sort_order)
editions(id PK, book_id FK, isbn13, isbn10, publisher, published_at, format,
         page_count, ol_edition_key, google_volume_id, metadata_json)
files(id PK, edition_id FK, path UNIQ, format, size_bytes, sha256, quality_id FK,
      date_added, date_scanned)
subjects(id PK, book_id FK, name, slug, source)     # genres/tags/keywords, facet dimension
book_fts(VIRTUAL TABLE — FTS5 over title, author, description, subjects)   # keyword search
indexers(id PK, name, type, base_url, api_key_enc, categories, priority, enabled,
         settings_json, last_rss_at, last_rss_result)
download_clients(id PK, name, type, host, port, username, password_enc, category,
                 priority, settings_json, enabled)
quality_profiles(id PK, name, allowed_formats JSON, cutoff JSON,
                 custom_formats JSON, language_prefs JSON, upgrade_allowed BOOL)
history(id PK, book_id FK?, event, release_title, indexer_id, download_id,
        timestamp, data_json)          # grabbed/imported/upgraded/failed/removed
queue(id PK, book_id FK, download_id, indexer_id, client_id, release_title,
      status, path, added_at, error)
metadata_cache(id PK, provider, kind, key, payload_json, fetched_at, etag)
settings(key PK, value)
users(id PK, username UNIQ, password_hash, api_key, role, oidc_sub?)
```

Notes:
- **`editions.isbn13` is the canonical join key** (§2.3 lesson 3). Provider IDs are plain columns/aliases, never identity.
- `metadata_json` on authors/books/editions = the raw last-known provider payload → offline re-render and future-proofing when providers change shape.
- **`files.sha256`** for dedupe and for the import-time "have we seen this file before" check.
- SQLite single-file = `*Arr`-style backup story (vacuums + copy while stopped).

### 4.3 Key flows

**A. Library import & enrichment (Phase 1).** `library_scan` walks the library folder → for each EPUB: `ebooklib` reads OPF (title, authors, ISBN, language, publisher, date, series from `<meta name="calibre:series">`) → upsert author/book/edition → `metadata.enrich` fetches covers/descriptions from providers (Open Library by ISBN → Google Books fallback) → cache. Bare PDFs: filename parsing + ISBN-in-filename. Calibre folder layout recognized by `metadata.db` presence (Phase 4 full sync; Phase 1 reads folders).

**B. RSS sync (Phase 2).** Every `rss_interval` (default 60 min): for each enabled indexer, `t=search&q=&cat=7000,7010,7030,7050&t=...` recent-releases query → parse releases → for each release, `parser.py` extracts candidate (author/title/format hints) → `matcher.py` scores against monitored books (FTS5 + normalized-title/author + ISBN when present) → above threshold → decision engine → grab. This is Sonarr's loop, restated for books.

**C. Search → grab → import (Phase 2).** Manual/automatic search: query all indexers (`t=search&q=<book+author>`), normalize candidates, run `decision.py` (order: format score per profile → custom-format score → protocol → indexer priority → seeds/peers → age → size; DRM'd/unknown-format candidates deprioritized, not banned), pick winner → push to download client with category `libarr` + label/book-id → record in `queue` → poll client API → on completion, `import_pipeline`: find file(s) in client's download dir → parse filename → verify against expected book (EPUB OPF ISBN/title match when parse is ambiguous) → **hardlink** (fallback copy) into `{root}/{Author}/{Series} - {Title} ({Year})/...` naming template → record `files` row → history event → notify → trigger OPDS/catalog refresh. Cutoff logic: if grabbed release < profile cutoff, mark still-wanted.

**D. Metadata enrichment (all phases).** `providers/*.py` each expose `search(q)`, `lookup(isbn)`, `get_work(ol_key)`, `covers(...)`; `normalize.py` maps to canonical models; `cache.py` wraps every call (TTL 30d, exponential backoff on 429/5xx, stale-while-error). Provider priority: Open Library → Google Books → (optional) ISBNdb. `dumps.py` (Phase 2.5) ingests OL monthly dumps into a local `metadata_cache` seed — **the app stays fully functional with zero internet metadata access.**

**E. Genre & keyword discovery (user-requested feature).** Two capabilities, one data model:
1. **Search**: `GET /api/v1/search?q=&genre=&year=&language=` — SQLite FTS5 over titles, author names, descriptions, and subjects; `genre` is a facet over the normalized `subjects` table. Subject sources: Open Library `subjects` (works API + dumps), Google Books `categories`, Calibre tags on import (Phase 4), user-editable.
2. **Monitor**: a *discovery import list* — a saved query (e.g. `subject:"science fiction"`, `year >= 2020`, `language:eng`) evaluated on a schedule (default weekly) against provider subject-search APIs; new top-N works are auto-added to wanted/monitored. This is the *Arr import-list pattern (Readarr: Goodreads lists; ours: provider-native queries).

Subject normalization lives in `metadata/subjects.py`: lowercased, trimmed, slugged, mapped through an alias thesaurus ("Sci-Fi" → "Science fiction") so facets stay clean; each row records its source (openlibrary / googlebooks / user / calibre) and is mergeable. Because Open Library dumps carry per-work subjects, genre facets and keyword search keep working fully offline once dumps are ingested (Phase 2.5).

---

## 5. Tech Stack Decision

**Recommended: Python 3.12 + FastAPI + SQLAlchemy 2 + SQLite + ARQ/Redis + Vue 3.**

| Criterion | Python (recommended) | C#/.NET (the *Arr way) | Node/TS |
|---|---|---|---|
| Ebook-tooling gravity | **Strong**: Calibre is Python; `ebooklib`, `feedparser`, `apprise`, `aiohttp` all first-class | Weak: every ebook lib is a port or CLI call | Weak |
| Ecosystem fit | CWA + LazyLibrarian + BookLore all Python → contributor/pattern reuse | Matches *Arr exactly; could cherry-pick Sonarr logic | — |
| Dev velocity (solo/community) | Very high | Medium (heavier ceremony) | High |
| Deployment | Single `python -m libarr`, or Docker | Self-contained binaries | Node image |
| Risks | GIL irrelevant here (I/O-bound); dep management (use `uv`) | Slower iteration; harder for the target community to contribute | Ebook libs thin; conversion story weaker |
| Realistic example | Calibre-Web-Automated | Sonarr/Readarr | BookLore (actually Go+React) |

Pinned libraries: `fastapi`, `uvicorn`, `sqlalchemy`, `alembic`, `pydantic-settings`, `ebooklib`, `feedparser`, `aiohttp`, `arq` + `redis`, `apscheduler`, `apprise`, `httpx`, `pytest`, `ruff`, `mypy`. Frontend: Vue 3 + Vite + Pinia (dark, *Arr-like dense tables; BookLore-style polish as a stretch).

**Licensing note:** GPL-3.0 for the project (matches ecosystem). Shell out to `ebook-convert` as a subprocess — do **not** embed Calibre code, which would force GPL-vs-clean-room headaches. Same for `kepubify`.

---

## 6. Implementation Phases

> Granularity note: Phases 0–1 are written as bite-sized TDD tasks (the skill's standard). Phases 2–4 are component-level (each component = 1–3 focused PRs); writing every sub-step now would be speculative — the plan's job is to make the *shape* obvious and each component independently shippable.

### Phase 0 — Scaffold (0.5–1 week)

- [x] **Task 0.1**: Init repo `libarr/` — `pyproject.toml` (uv), `src/libarr` layout, `ruff`/`mypy` config, `.gitignore`, README.
- [x] **Task 0.2**: `uv init` + `uv add fastapi uvicorn sqlalchemy alembic pydantic-settings ebooklib feedparser aiohttp arq apscheduler apprise httpx`; pin `python = ">=3.12,<3.13"`.
- [x] **Task 0.3**: `main.py` app factory with `/api/v1/health` returning `{"status":"ok","version":...}`; test: `pytest tests/test_health.py` → 200. Commit: `feat: scaffold fastapi app`.
- [x] **Task 0.4**: SQLAlchemy engine + session factory, WAL pragma, `alembic init`; empty migration applies cleanly. Test: `tests/test_db.py` round-trips a `settings` row. Commit.
- [x] **Task 0.5**: `config.py` (pydantic-settings): `data_dir`, `library_root`, `download_dir`, `redis_url`, `rss_interval`, `auth`. Defaults sensible for docker; env overrides.
- [x] **Task 0.6**: `docker/` — multi-stage Dockerfile, `docker-compose.yml` with **single `/data` volume** (hardlink law, §2.1) + redis; `docker-compose.dev.yml` with live reload. Commit: `feat: docker packaging`.
- [x] **Task 0.7**: GitHub Actions: `uv sync` + `ruff check` + `mypy` + `pytest` on push/PR. Test CI passes. Commit.
- [x] **Task 0.8**: SPA scaffold `web/` (Vite + Vue 3 + dark theme), empty shell routing, CI build. Commit.

### Phase 1 — Libarr Lite: library, metadata, serving (2–3 weeks)

- [x] **Task 1.1**: ORM models `Author`, `Book`, `Series`, `Edition`, `File`, `Subject` + `book_fts` FTS5 virtual table (§4.2) + alembic migration. Test: model CRUD + constraints + subject upsert.
- [x] **Task 1.2**: `library_scan.scan_folder()` — walk `library_root`, index files by extension, upsert minimal records, record `sha256`. Tests: tmp-dir fixture with 3 generated EPUBs (build via `ebooklib` helper, see `tests/fixtures/make_epub.py`), assert records + dedupe.
- [x] **Task 1.3**: `parser.py` book filename parser: regex rules for `Title - Author`, `Series #N - Title`, `Title (Year)`, ISBN-in-name; pure function + table-driven tests (reuse real-world release-name samples collected from tracker listings in `tests/fixtures/release_names.txt`).
- [x] **Task 1.4**: `metadata/providers/openlibrary.py` + `googlebooks.py` + `normalize.py` + `cache.py`. Tests with `respx`/`vcr` fixtures: normalize a real OL payload; cache hit/miss; 429 → backoff → stale-while-error.
- [x] **Task 1.5**: `metadata/matcher.py` — ISBN-exact → normalized-title+author (unicode-fold, strip punctuation) → FTS5 fallback; score threshold constants. Tests incl. "two editions, same work" merge and "same title, different author" non-merge.
- [x] **Task 1.6**: enrichment worker task: for each unenriched book, lookup by ISBN → fill description/**subjects (genres/keywords from OL `subjects` + Google `categories`)**/cover/series/year; covers extracted from EPUB OPF when provider cover missing. Tests with fixture payloads.
- [x] **Task 1.7**: API: `GET /authors`, `GET /authors/{id}`, `GET /books`, `GET /books/{id}`, `GET /books/{id}/file`, `PATCH /books/{id}` (edit metadata). Tests: CRUD + pagination.
- [x] **Task 1.7b**: **Genre & keyword search**: `metadata/subjects.py` (normalize/slug/alias-thesaurus) + `book_fts` triggers + `GET /api/v1/search?q=&genre=&year=&language=` with facet counts. Tests: 3 fixture books → keyword hit, genre facet counts, alias match ("sci-fi" → Science fiction), empty-query 400.
- [x] **Task 1.8**: `library/opds.py` — OPDS 1.2 root + by-author + search + acquisition entries (`application/epub+zip`); OPDS 2.0 JSON in Phase 2. Tests: parse generated feed, assert required Atom namespaces/links.
- [x] **Task 1.9**: `library/reader.py` — stream EPUB (with `Content-Disposition`), reading-progress endpoint (position per user), PDF streaming. Tests: range/simple GETs.
- [x] **Task 1.10**: `library/covers.py` — cover endpoint, local cover cache dir, EPUB cover extraction. Test: generated EPUB → cover bytes returned.
- [x] **Task 1.11**: Auth: forced login (hash `argon2` via `pwdlib`), first-run admin bootstrap, API-key auth for integrations, CSRF-safe cookie sessions. Tests: unauthenticated → 401; bootstrap flow.
- [x] **Task 1.12**: Frontend: library grid + book detail + edit metadata + reader route + OPDS links visible + **search bar with genre/keyword query + genre facet browse**. Manual E2E: KOReader/Kobo browser hits OPDS, downloads a book. Commit.
- [x] **Task 1.13**: Notifications wiring (Apprise) for import/enrich events. Test: fake apprise transport records payload.
- [ ] **Milestone 1**: "Libarr Lite" — point at folder, get browsable, searchable, OPDS-served, cover-rich library. **This is already a shippable Calibre-Web alternative.**

### Phase 2 — The *Arr core: acquisition (4–6 weeks)

**2.1 Indexer layer**
- [x] Torznab/Newznab client (ET-based parse; feedparser collapses repeated torznab:attr tags) RSS + JSON API): `search(q, cat)`, `recent(cat)`, capability introspection; adapter class + `indexers/registry.py`.
- [x] Indexer CRUD API + test endpoint ("Test" button) like *Arr.
- [x] `tasks.rss_sync` — per-indexer interval loop, per-indexer failure isolation (one dead indexer never blocks others). Tests: mock indexer fixture (see §8) returns feed → assert wanted-match grabbed.
- [x] Ship **built-in legal sources**: Gutenberg + Open Library/IA as first-class indexers `metadata/providers/gutenberg.py` + `standardebooks.py` as first-class *indexers* (direct download links as "releases") — acquisition works out of the box, no piracy required, day one. **2026-08-19 note:** Standard Ebooks moved its OPDS feeds behind auth (401s for programmatic access) — replaced with an **Open Library + Internet Archive** adapter (search.json + `archive.org/download/{ia}/{ia}.epub`); Gutenberg's official endpoint serves a legacy JSON array (not gutendex), parsed accordingly.

**2.2 Download clients**
- [x] Adapters: qBittorrent (Web API v2), Deluge (JSON-RPC), Transmission (RPC), SABnzbd, NZBGet — each: `add(release)`, `list(category)`, `remove(download_id)`, `status`. Category constant `libarr`. Tests: mocked HTTP fixtures per client.
- [x] Client CRUD API + connectivity test; Remote Path Mapping fields (remote_path/local_path); UI pending with frontend pass (`downloads/` → library-side path translation).
- [x] `tasks.download_watch` — poll clients; state machine queued→downloading→importing→imported/failed; state machine `downloading → complete → imported → (seed policy) removed`.

**2.3 Decision engine**
- [x] `quality.py` — format taxonomy (EPUB > AZW3/MOBI > PDF > others; audiobook profile: M4B > MP3 > others) + quality profile model: allowed formats, cutoff, custom formats (e.g. `+Retail`, `+DRM-Free`, `-Unknown`, `-Sample`, narrator scoring for audiobooks), language prefs.
- [x] `decision.py` — comparer implementing: **Format score → Custom-format score → Protocol (delay profile) → Indexer priority → Seeds/Peers → Age → Size** (Sonarr order, book-flavored). Unit tests: pairwise rankings, cutoff semantics, upgrade eligibility.
- [x] Release candidates normalization: parse release title + size + seeders into `Candidate`; filter obvious junk (`candidates_fixtures.json` corpus) (`[sample]`, `.txt` scans, password-protected) — tests with a `candidates_fixtures.json` corpus.

**2.4 Import pipeline**
- [x] `import_pipeline.py` — locate completed files (remote-path-mapped) → OPF verify → hardlink/copy/move → naming template → File row → quarantine → notify → `parser.py` → `matcher.py` → verify via EPUB OPF (ISBN/title check when ambiguity > threshold) → **hardlink→rename** (fallback: copy; config: move) → write `files` row + history → refresh OPDS index → notify. Tests: end-to-end with a real temp filesystem, assert hardlink inode equality, naming template output, failure paths (no-match → quarantine dir + UI flag).
- [x] Naming templates (token rendering `{Author Name}/{Series}/{Book Title}/{Release Year}/{Author}/{Extension}`; UI pending with frontend pass) `{Author Name}/{Series} - {Book Title} ({Release Year})/{Series} - {Book Title} ({Release Year}) - {Author}.{Extension}` default; token rendering + tests.

**2.5 Wanted / monitoring / history**
- [x] Wanted API+UI: Missing + Cutoff Unmet lists, per-item "Search now" (frontend Wanted view); batch-search politeness pending scheduler pass.
- [x] History API+UI (grab/import/upgrade/fail/discovery) with filters; `history_events` table seeded from pipeline events.
- [x] Per-book/author "monitor" toggle driving RSS eligibility; `books.monitored` + `authors.monitored` (PATCH /authors/{id}).
- [x] Upgrade loop: RSS releases beating the current file below cutoff are queued; import records `upgrade` history (old file kept — seed-friendly default).

**2.6 Genre & keyword discovery & monitoring**
- [x] `metadata/subjects.py` normalization + alias thesaurus with table-driven tests.
- [x] Provider subject-search adapters: OL `subject:` (search_subject) + Google Books `q=subject:`; works deduped against the library on import.
- [x] Discovery API + UI (frontend Discover view): genre/keyword/year/language → live preview → add N to library (monitored). Live-verified: 50 fantasy works imported end-to-end.
- [x] Saved discovery lists (import lists): schedule_days, max_per_run, auto_monitor, last_run_at + POST /system/discovery-lists trigger; tests assert additions + dedupe.
- [x] Frontend: genre browse (Search facets) + Discover view (query builder + saved-lists panel).

**Milestone 2**: full *Arr parity for ebooks: `add author → monitor → RSS/search → grab → import → named library → OPDS → device` with quality upgrades.

### Phase 2.5 — Metadata resilience hardening (1 week, do *not* skip)

- [x] `dumps.py`: streaming, resumable OL dump ingestion (works/authors/editions → `dump_rows` + `dump_isbns` ISBN index); `libarr metadata-import --dump ...` CLI (self-migrating); provider-down fallback: ISBN lookups resolve fully offline through the mirror.
- [ ] Provider health dashboard (API status, last-success, cache hit rate, per-provider error counts) in System UI — *operational transparency is the anti-Readarr feature*.
- [ ] `libarr export/import` for metadata state (JSON/zip) so users can migrate instances.
- [ ] Failure drills: tests that simulate provider-down (stale-while-error serves last-known payloads), provider-shape-change (schema drift tolerated via `metadata_json`), rate-limit storms.

### Phase 3 — Ecosystem polish (3–4 weeks)
- [x] Request UI (Overseerr-style: "request book" → auto-add+search) with per-user limits; import lists (Open Library shelf / StoryGraph / Goodreads CSV export; Prowlarr-style "import" flow). — Request flow shipped (POST /requests: ISBN→provider or title→OL search, auto-add monitored, search-now). Per-user limits + external import lists still pending.
- [x] Conversion worker: `ebook-convert` subprocess queue (EPUB→AZW3/KEPUB/PDF per device targets), configurable per format, disk guards. — `conversion.py` + `conversion_jobs` table + POST /books/{id}/convert + GET /conversions + scheduler cycle; disk guard (500MB cap), GPL-clean subprocess.
- [x] Kobo KEPUB pass (kepubify subprocess — conversion worker routes KEPUB targets to kepubify) + Send-to-Kindle email (SMTP bridge, POST /books/{id}/send-to-kindle) + KOReader progress sync (koreader-sync-server-compatible /koreader endpoints: users/auth, users/lastone, progress/upload, progress/get; API keys as sync tokens).
- [x] Calendar (upcoming releases for monitored authors) — `calendar.py` from OL author search (year granularity, honest about OL's data), GET /calendar + Calendar UI.
- [x] Unpack archives (zip/rar torrent payloads) before import (unpackerr-equivalent, in-worker). — zip/tar with zip-slip protection in the import locate step; rar pending unrar binary.
- [x] Notifications for search/failed-import; per-user notification prefs. — search-now outcomes notify per `users.notify_events` prefs; import/fail events already notify globally.

### Phase 4 — Scale & compat (ongoing)
- [x] Calibre `metadata.db` compatibility: READ import (POST /system/import-calibre) + `calibredb` CLI export bridge (POST /system/export-calibre) — Calibre stays authoritative, Libarr only adds.
- [x] Multi-user: admin/user roles (require_admin, users API, self-demote guard) + per-user shelves (CRUD + book membership, user-scoped). OIDC deferred (needs an IdP to test against).
- [x] Postgres backend: LIVE-VERIFIED on real Postgres 16 (Docker): all 14 migrations apply; dump ingestion, ILIKE search, matcher fallback, offline ISBN resolution all work. FTS is dialect-aware (FTS5 on SQLite, ILIKE on PG; tsvector parity deferred).
- Modular split: run `metadata`, `indexers`, `core` as separate processes over a shared API+DB (the "real stack" deployment) — the module seams from day one make this mechanical.
- Plugin system (indexer/client/provider hooks) — deferred until community signals a need (YAGNI now).

---

## 7. Files That Will Change (Phase 1–2 hotspots)

Covered per-task above; the invariants to respect from here on:
- `libarr/models/*` changes **always** ship with an alembic migration + test.
- `libarr/metadata/*` — no direct external HTTP outside providers; everything through `cache.py` (the anti-Readarr rule, enforced by review, later by a lint rule).
- `libarr/acquisition/decision.py` stays a pure function of (profile, candidates) — no I/O — so ranking is exhaustively unit-testable.

---

## 8. Testing & Validation Strategy

- **Unit**: pytest + tmp_path fixtures; pure functions (parser, matcher, decision, naming) get table-driven tests with real-world release-name corpus (`tests/fixtures/release_names.txt`) — this corpus is the product's quality floor.
- **Integration**: `respx` (aiohttp mocking) for providers/indexers/clients with recorded fixtures (`vcr`-style YAML). Generated EPUB fixtures via `tests/fixtures/make_epub.py` (ebooklib) so import/enrichment tests never need real files.
- **E2E (Phase 2)**: `docker-compose.test.yml` — app + redis + **qBittorrent** + **mock Torznab indexer** (a tiny FastAPI fixture that serves a scripted release list). The canonical acceptance test: *seed mock indexer with "Stephen King - The Stand (2025).epub" → add author in UI → assert file appears in library with correct name and a history event* — this is the whole product in one test.
- **Metadata drills** (§2.3 / Phase 2.5): provider-down, shape-change, rate-limit tests run in CI.
- **Manual device testing checklist** (docs/device-testing.md): KOReader OPDS, Kobo browser OPDS, Kindle send-to-kindle, browser reader — human-run before each release.
- **Performance guard**: scan of 10k-EPUB fixture library (script-generated) completes < 2 min; RSS diff over 10k monitored titles < 5 s. CI smoke test.

---

## 9. Deployment & Packaging

- Docker images (linuxserver-style: `PUID`/`PGID`, `/config` + `/data` mounts), official compose with the **single `/data` volume** layout:
  ```yaml
  volumes:
    - ./data:/data        # /data/books, /data/downloads, /data/config
  ```
- Bare-metal: `pipx`/`uv tool` + systemd unit (wiki example).
- Update channel: rolling tag + `stable`; alembic migrations run automatically on boot with pre-backup.
- Backup story: stop → copy SQLite + `/config` + library (hardlinks make library copies cheap).

---

## 10. Risks, Tradeoffs & Mitigations

| Risk | Mitigation |
|---|---|
| **Metadata provider instability** (killed Readarr) | Multi-provider + local cache + dump import + health dashboard + `metadata_json` drift tolerance. This is the #1 design pillar (§2.3). |
| Book identification is genuinely harder than TV (no episode numbers; editions galore) | ISBN-first join key; OPF verification at import; fuzzy matcher with strict thresholds; quarantine + human-fix flow instead of wrong placement. |
| Legal posture of download automation | Same as every *Arr app: neutral infrastructure, user-configured sources; **ship legal indexers by default** (Gutenberg, Standard Ebooks, Open Library). No DRM-circumvention features. A clear docs page on operator responsibility. |
| Format sprawl (EPUB variants, DRM'd files, comics, audiobooks) | Quality profiles make format a *policy*, not a fork; conversion worker later; DRM'd files flagged `+DRM` custom format (deprioritized) rather than banned. |
| Scope creep into "the whole stack" | Modular monolith; Phases are cut so each milestone is shippable (Lite is a Calibre-Web alternative; Phase 2 is the *Arr). Request UI/audiobooks/comics explicitly deferred. |
| Community adoption (self-hosted projects live or die on it) | Torznab/Newznab compat day one (existing Prowlarr/Jackett users); OPDS day one (existing reader apps); Calibre-compat path; GPL; docs wiki; docker compose one-liner. |
| GPL contamination via Calibre tooling | Subprocess-only use of `ebook-convert`/`kepubify`; no embedded code (license boundary documented in CONTRIBUTING). |
| Single-maintainer bus factor | Bite-sized, well-fixtured codebase; the decision engine/parser/matcher are pure functions — low-barrier contribution surface; community-first roadmap (this is an OSS project, not a startup). |

---

## 11. Open Questions (need your call before Phase 0/1)

1. **Tech stack** — Python/FastAPI recommended (§5). Prefer C#/.NET (closer to Sonarr) or Go? (Changes Phase 0 wholesale; everything else survives.)
2. **Form factor** — all-in-one app (recommended) vs separate processes mirroring *Arr exactly? (We build modular-monolith either way; this decides default packaging.)
3. **Frontend** — Vue 3 SPA (recommended, BookLore-polish) vs HTMX/server-rendered for a faster MVP? (Affects Phase 1.12, not the backend.)
4. **Audiobooks in v1?** — Readarr promised them; they're a real chunk of demand. Recommend: v1 = ebooks only, audiobooks as Phase 3 media type. 
5. **Calibre compatibility depth** — folder-scan only (fast) vs full `metadata.db` read/write in Phase 1? Recommend: folder-scan for MVP, DB compat in Phase 4.
6. **Project name** — `libarr` is a working title; alternatives: `bookarr`, `shelfarr`, `folioarr`, `litarr`. (Naming matters for the community project.)
7. **Funding/org** — plain GitHub OSS vs a GitHub org with sponsors (CWA-style ko-fi)? Not blocking; decides repo home.

---

## 12. Key References

- Readarr retirement announcement + metadata issues: readarr.com · wiki.servarr.com/readarr/metadata-issues
- Servarr wiki (Sonarr FAQ — find-loop, decision order, hardlink/docker guide): wiki.servarr.com
- Complete *Arr stack guide (workflow diagram): bytesized-hosting.com/guides/the-complete-arr-stack-guide-2026
- Calibre-Web-Automated (the all-in-one incumbent): github.com/crocodilestick/calibre-web-automated
- BookLore (modern library-server benchmark): github.com/booklore-app/booklore
- Open Library developer docs + data dumps: openlibrary.org/developers · Google Books API: developers.google.com/books · ISBNdb API docs: isbndb.com/apidocs/v2
- OPDS 1.2 / 2.0 specs: opds.io · ebooklib: github.com/aerkalov/ebooklib · Apprise: github.com/caronc/apprise
- Sonarr decision comparer source (ranking order): github.com/Sonarr/Sonarr/blob/develop/src/NzbDrone.Core/DecisionEngine/DownloadDecisionComparer.cs
- TRaSH Guides (quality profiles / custom formats pattern): trash-guides.info
