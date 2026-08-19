"""Queue processing (plan 2.2): grab queued items into the download client,
then watch for completion and hand off to the import pipeline.

State machine: queued → downloading → importing → imported | failed.
The import hook (set in 2.4) receives (session, queue_item, client_item);
until then, completed downloads are marked imported directly.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from libarr.clients.base import ClientItem, DownloadError
from libarr.clients.registry import build_client
from libarr.models import DownloadClientRow, QueueItem

ImportHook = Callable[[Session, QueueItem, ClientItem], None]


def process_queue(session: Session, *, import_hook: ImportHook | None = None) -> dict[str, int]:
    """Grab + watch one cycle across all enabled clients. Per-client isolation:
    a dead client is skipped, never fatal."""
    stats = {"grabbed": 0, "completed": 0, "failed": 0}
    rows = session.scalars(
        select(DownloadClientRow).where(DownloadClientRow.enabled.is_(True))
    ).all()
    if not rows:
        return stats

    # 1. Grab: hand queued items to the highest-priority enabled client.
    # Manual items (e.g. Anna's Archive links) are bookmarks for the user —
    # never pushed to a download client.
    client = build_client(rows[0])
    queued = session.scalars(
        select(QueueItem).where(QueueItem.status == "queued", QueueItem.manual.is_(False))
    ).all()
    for item in queued:
        if not item.download_url:
            item.status = "failed"
            item.error = "no download URL"
            stats["failed"] += 1
            continue
        try:
            item.client_download_id = client.add_url(item.download_url)
            item.client_name = client.name
            item.status = "downloading"
            stats["grabbed"] += 1
        except DownloadError as exc:
            item.status = "failed"
            item.error = str(exc)
            stats["failed"] += 1
    session.commit()

    # 2. Watch: poll every enabled client for state changes.
    for row in rows:
        try:
            items = build_client(row).list_items()
        except DownloadError:
            continue  # one dead client never blocks the rest
        by_id = {item.id: item for item in items}
        active = session.scalars(
            select(QueueItem).where(
                QueueItem.status == "downloading",
                QueueItem.client_name == row.name,
            )
        ).all()
        for queue_item in active:
            client_item = by_id.get(queue_item.client_download_id or "")
            if client_item is None:
                continue  # not visible to the client yet
            if client_item.status == "error":
                queue_item.status = "failed"
                queue_item.error = "download client reported an error"
                stats["failed"] += 1
            elif client_item.status == "complete":
                queue_item.status = "importing"
                if import_hook is not None:
                    try:
                        import_hook(session, queue_item, client_item)
                    except Exception as exc:  # noqa: BLE001 — hook failure is per-item
                        queue_item.status = "failed"
                        queue_item.error = f"import failed: {exc}"
                        stats["failed"] += 1
                else:
                    queue_item.status = "imported"
                stats["completed"] += 1
        session.commit()
    return stats
