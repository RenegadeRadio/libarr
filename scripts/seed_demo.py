"""Dev tool: seed a demo library, scan it, enrich from real providers.

Usage: uv run python scripts/seed_demo.py
Creates data/books/*.epub (gitignored), scans them into the dev database
(data/libarr.db), then runs the enrichment worker against Open Library.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libarr.acquisition.library_scan import scan_library
from libarr.db import make_engine, session_factory
from libarr.metadata.enrich import enrich_library
from tests.fixtures.make_epub import make_epub

DEMO_BOOKS = [
    ("The Stand - Stephen King (1990).epub", "The Stand", "Stephen King", "9780451169518"),
    ("Dune - Frank Herbert (1965).epub", "Dune", "Frank Herbert", "9780441172719"),
    ("Neuromancer (1984) - William Gibson.pdf", None, None, None),
]


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    library_root = root / "data" / "books"
    library_root.mkdir(parents=True, exist_ok=True)

    for filename, title, author, isbn in DEMO_BOOKS:
        path = library_root / filename
        if not path.exists():
            if title:
                make_epub(path, title, author, isbn=isbn)
            else:
                path.write_bytes(b"%PDF-1.4 demo placeholder")
            print(f"created {path.name}")

    engine = make_engine(f"sqlite:///{root / 'data' / 'libarr.db'}")
    with session_factory(engine)() as session:
        scan = scan_library(session, library_root)
        print(f"scan: {scan}")
        enriched = enrich_library(session)
        print(f"enriched: {enriched} books")


if __name__ == "__main__":
    main()
