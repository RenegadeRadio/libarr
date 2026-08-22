"""Libarr command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from libarr.config import Settings
from libarr.db import make_engine, session_factory
from libarr.metadata.dumps import DUMP_KINDS, ingest_dump
from libarr.scheduler import run_cycles, scheduler_loop


def _infer_kind(path: Path) -> str | None:
    name = path.name.lower()
    for plural in ("works", "editions", "authors"):
        if plural in name:
            return plural[:-1]  # plural filename → singular kind
    return None


def _migrations_dir() -> Path:
    """Locate the alembic scripts (env override → source tree → image path)."""
    env = os.environ.get("LIBARR_MIGRATIONS_DIR")
    if env:
        return Path(env)
    source_tree = Path(__file__).resolve().parents[2] / "migrations"
    if (source_tree / "env.py").is_file():
        return source_tree
    image_path = Path("/app/migrations")
    if (image_path / "env.py").is_file():
        return image_path
    return source_tree


def _ensure_migrated(database_url: str) -> None:
    """Run pending Alembic migrations (idempotent) so the CLI works on a
    fresh or outdated database without a separate `alembic upgrade head`."""
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(_migrations_dir()))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="libarr", description="Libarr — self-hosted ebook automation"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    importer = subparsers.add_parser("metadata-import", help="Ingest Open Library dump files")
    importer.add_argument("--dump", type=Path, required=True, help="path to an ol_dump_*.txt file")
    importer.add_argument(
        "--kind",
        choices=DUMP_KINDS,
        help="record kind (default: inferred from the filename)",
    )

    exporter = subparsers.add_parser(
        "export", help="Export the portable metadata catalog to JSON or ZIP"
    )
    exporter.add_argument("--output", "-o", type=Path, required=True)
    exporter.add_argument("--force", action="store_true", help="overwrite an existing output file")

    restore = subparsers.add_parser("import", help="Import a Libarr metadata JSON or ZIP archive")
    restore.add_argument("--input", "-i", type=Path, required=True)
    restore.add_argument(
        "--replace", action="store_true", help="replace an existing metadata catalog"
    )

    worker = subparsers.add_parser(
        "worker",
        help=(
            "Background jobs process (Phase 4 modular split): RSS, downloads, discovery, conversion"
        ),
    )
    worker.add_argument(
        "--once",
        action="store_true",
        help="run a single cycle and exit (cron-friendly) instead of looping",
    )
    worker.add_argument(
        "--interval",
        type=int,
        help="cycle interval in seconds (default: the LIBARR_SCHEDULER_INTERVAL_SECONDS setting)",
    )

    args = parser.parse_args(argv)

    if args.command in {"export", "import"}:
        from libarr.metadata.backup import import_archive, write_export

        settings = Settings()
        _ensure_migrated(settings.database_url)
        engine = make_engine(settings.database_url)
        try:
            with session_factory(engine)() as session:
                if args.command == "export":
                    counts = write_export(session, args.output, force=args.force)
                    print(f"exported {sum(counts.values())} record(s) to {args.output}")
                else:
                    counts = import_archive(session, args.input, replace=args.replace)
                    print(f"imported {sum(counts.values())} record(s) from {args.input}")
            return 0
        finally:
            engine.dispose()

    if args.command == "worker":
        settings = Settings()
        _ensure_migrated(settings.database_url)
        engine = make_engine(settings.database_url)
        if args.once:
            stats = run_cycles(engine)
            print(f"cycle done: {stats}")
            engine.dispose()
            return 0
        interval = float(args.interval or settings.scheduler_interval_seconds)
        asyncio.run(
            scheduler_loop(
                engine,
                interval_seconds=interval,
                jitter_seconds=float(settings.scheduler_jitter_seconds),
            )
        )
        return 0

    if args.command == "metadata-import":
        kind = args.kind or _infer_kind(args.dump)
        if kind is None:
            print(
                "could not infer record kind from filename; pass --kind work|edition|author",
                file=sys.stderr,
            )
            return 2
        settings = Settings()
        _ensure_migrated(settings.database_url)
        engine = make_engine(settings.database_url)
        with session_factory(engine)() as session:
            count = ingest_dump(session, args.dump, kind=kind)
        print(f"ingested {count} {kind} record(s) from {args.dump}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
