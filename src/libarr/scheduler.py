"""In-process background scheduler (plan: scheduler.py → tasks).

Runs the three monitoring cycles on cadence with jitter and per-cycle
failure isolation: RSS sync (indexers → wanted queue), the download
watch (grab → import hook), and discovery lists (genre import lists).

Every job is a plain session-injected function, so this loop can later be
replaced by an ARQ/Redis worker without touching the jobs themselves.
"""

from __future__ import annotations

import asyncio
import logging
import random

from sqlalchemy.engine import Engine

from libarr.acquisition.import_pipeline import default_import_hook
from libarr.db import session_factory
from libarr.discovery import evaluate_lists
from libarr.tasks.download_watch import process_queue
from libarr.tasks.rss import rss_sync

logger = logging.getLogger(__name__)


def run_cycles(engine: Engine) -> dict[str, object]:
    """One full monitoring cycle; returns per-job stats.

    A broken job is logged and isolated — it never prevents the other
    cycles from running (the *Arr resilience doctrine).
    """
    stats: dict[str, object] = {}
    with session_factory(engine)() as session:
        try:
            stats["rss"] = rss_sync(session)
        except Exception:  # noqa: BLE001 — isolation by design
            logger.exception("scheduler: rss_sync failed")
            stats["rss"] = "error"
        try:
            stats["queue"] = process_queue(session, import_hook=default_import_hook)
        except Exception:  # noqa: BLE001
            logger.exception("scheduler: process_queue failed")
            stats["queue"] = "error"
        try:
            stats["discovery"] = evaluate_lists(session)
        except Exception:  # noqa: BLE001
            logger.exception("scheduler: evaluate_lists failed")
            stats["discovery"] = "error"
    return stats


async def scheduler_loop(
    engine: Engine,
    *,
    interval_seconds: float,
    jitter_seconds: float = 60.0,
    min_delay: float = 1.0,
) -> None:
    """Run cycles forever: interval ± jitter between runs (plan 2.1.3)."""
    while True:
        try:
            await asyncio.to_thread(run_cycles, engine)
        except Exception:  # noqa: BLE001 — belt-and-braces (e.g. DB lock)
            logger.exception("scheduler cycle failed")
        delay = max(min_delay, interval_seconds + random.uniform(-jitter_seconds, jitter_seconds))
        await asyncio.sleep(delay)
