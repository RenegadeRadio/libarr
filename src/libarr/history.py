"""Pipeline history log (plan 2.5): grab / import / upgrade / fail / discovery."""

from __future__ import annotations

from sqlalchemy.orm import Session

from libarr.models import HistoryEvent


def record(
    session: Session,
    *,
    kind: str,
    title: str,
    book_id: int | None = None,
    details: str | None = None,
) -> None:
    session.add(HistoryEvent(kind=kind, title=title, book_id=book_id, details=details))
