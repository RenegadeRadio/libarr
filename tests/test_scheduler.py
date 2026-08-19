"""Phase 2.5 — scheduler: cadence loop, cycle isolation, lifespan wiring."""

import asyncio
import random
from contextlib import suppress

import respx
from httpx import Response
from sqlalchemy import select

import libarr.scheduler as scheduler
from libarr.db import session_factory
from libarr.models import Author, Book, Indexer, QueueItem
from libarr.scheduler import run_cycles, scheduler_loop

_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Dune - Frank Herbert (1965) EPUB</title>
      <guid isPermaLink="false">g1</guid>
      <link>http://tracker.example/d/1</link>
      <enclosure url="http://tracker.example/d/1.torrent" length="1000"/>
      <torznab:attr name="size" value="1000"/>
      <torznab:attr name="seeders" value="10"/>
    </item>
  </channel>
</rss>"""


@respx.mock
def test_run_cycles_runs_all_jobs(client, db):
    client, db = client
    with session_factory(db)() as session:
        author = Author(name="Frank Herbert", monitored=True)
        session.add_all([author, Book(title="Dune", author=author, monitored=True)])
        session.add(
            Indexer(name="idx", kind="torznab", url="http://idx.example", categories="7000")
        )
        session.commit()

    respx.get(url__startswith="http://idx.example/api").mock(return_value=Response(200, text=_RSS))

    stats = run_cycles(db)

    assert set(stats) == {"rss", "queue", "discovery", "conversions"}
    assert stats["rss"] == {"idx": 1}
    with session_factory(db)() as session:
        assert session.scalars(select(QueueItem)).first() is not None


def test_run_cycles_isolates_failing_job(client, db, monkeypatch):
    client, db = client
    calls = {"queue": 0, "discovery": 0}

    def _boom(session):
        raise RuntimeError("rss exploded")

    def _queue(session, import_hook=None):
        calls["queue"] += 1
        return {"ok": True}

    def _discovery(session):
        calls["discovery"] += 1
        return {}

    def _conversions(session, out_dir="data/converted"):
        return {"completed": 0, "failed": 0}

    monkeypatch.setattr(scheduler, "rss_sync", _boom)
    monkeypatch.setattr(scheduler, "process_queue", _queue)
    monkeypatch.setattr(scheduler, "evaluate_lists", _discovery)
    monkeypatch.setattr(scheduler, "process_conversions", _conversions)

    stats = run_cycles(db)

    assert stats["rss"] == "error"
    assert calls == {"queue": 1, "discovery": 1}


def test_scheduler_loop_runs_and_can_be_cancelled(client, db, monkeypatch):
    client, db = client
    runs = {"n": 0}

    def _run_cycles(engine):
        runs["n"] += 1

    monkeypatch.setattr(scheduler, "run_cycles", _run_cycles)
    monkeypatch.setattr(scheduler, "random", random.Random(0))

    async def _drive() -> None:
        task = asyncio.create_task(
            scheduler_loop(db, interval_seconds=0.05, jitter_seconds=0.0, min_delay=0.0)
        )
        await asyncio.sleep(0.18)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    asyncio.run(_drive())

    assert runs["n"] >= 2  # ran on cadence until cancelled
