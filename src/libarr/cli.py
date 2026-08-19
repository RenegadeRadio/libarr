"""Libarr CLI (plan 2.5): `libarr metadata-import --dump <file> [--kind ...]`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from libarr.config import Settings
from libarr.db import make_engine, session_factory
from libarr.metadata.dumps import DUMP_KINDS, ingest_dump


def _infer_kind(path: Path) -> str | None:
    name = path.name.lower()
    for plural in ("works", "editions", "authors"):
        if plural in name:
            return plural[:-1]  # plural filename → singular kind
    return None


def _ensure_migrated(database_url: str) -> None:
    """Run pending Alembic migrations (idempotent) so the CLI works on a
    fresh or outdated database without a separate `alembic upgrade head`."""
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[2] / "migrations"),
    )
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

    args = parser.parse_args(argv)

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
