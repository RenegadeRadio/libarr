"""KOReader progress sync (Phase 3) — a koreader-sync-server-compatible subset.

Exposes the four endpoints KOReader's "Sync reading progress" plugin calls
against a self-hosted koreader-sync-server, mounted at /koreader:

    POST /users/auth        {"user", "password", "device_id"} → token
    POST /users/lastone     {"token"} → last-read info (minimal)
    POST /progress/upload   {"token", "progress": {...}}      → {ok}
    POST /progress/get      {"token", "documents": [...]}     → stored progress

Auth: the KOReader app stores whatever token the server returns and sends it
with every call. We return the user's API key as the token, so the existing
account system doubles as the sync credential store.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from libarr.api.auth import verify_password
from libarr.api.deps import get_session
from libarr.models import KoreaderProgress, User

router = APIRouter(prefix="/koreader", tags=["koreader"])


def _user_by_token(session: Session, token: str | None) -> User | None:
    if not token:
        return None
    return session.scalars(select(User).where(User.api_key == token)).first()


def _respond(payload: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, **payload}


@router.post("/users/auth")
def koreader_auth(
    body: dict[str, Any], session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    user = session.scalars(select(User).where(User.username == str(body.get("user", "")))).first()
    if user is None or not verify_password(str(body.get("password", "")), user.password_hash):
        return {"ok": False, "error": "Invalid credentials"}
    return _respond(
        {
            "token": user.api_key or "",
            "user": {"id": user.id, "username": user.username, "settings": {"sync": True}},
        }
    )


@router.post("/users/lastone")
def koreader_lastone(
    body: dict[str, Any], session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    user = _user_by_token(session, body.get("token"))
    if user is None:
        return {"ok": False}
    row = session.scalars(
        select(KoreaderProgress)
        .where(KoreaderProgress.user_id == user.id)
        .order_by(KoreaderProgress.updated_at.desc())
    ).first()
    return _respond(
        {
            "user": user.username,
            "document": row.document if row else None,
            "title": row.title if row else None,
            "progress": row.progress if row else None,
            "time": 0,
        }
    )


@router.post("/progress/upload")
def koreader_progress_upload(
    body: dict[str, Any], session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    user = _user_by_token(session, body.get("token"))
    if user is None:
        return {"ok": False, "error": "Invalid token"}
    progress = body.get("progress") or {}
    document = str(progress.get("document") or "")
    if not document:
        return {"ok": False, "error": "Missing document"}

    row = session.scalars(
        select(KoreaderProgress).where(
            KoreaderProgress.user_id == user.id, KoreaderProgress.document == document
        )
    ).first()
    if row is None:
        row = KoreaderProgress(user_id=user.id, document=document)
        session.add(row)
    row.title = progress.get("title")
    row.progress = float(progress.get("progress") or 0.0)
    row.device = progress.get("device")
    row.client = progress.get("client")
    session.commit()
    return _respond({"results": [{"ok": True}]})


@router.post("/progress/get")
def koreader_progress_get(
    body: dict[str, Any], session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    user = _user_by_token(session, body.get("token"))
    if user is None:
        return {"ok": False, "error": "Invalid token"}
    documents = [str(d) for d in (body.get("documents") or [])]
    rows = session.scalars(
        select(KoreaderProgress).where(
            KoreaderProgress.user_id == user.id, KoreaderProgress.document.in_(documents)
        )
    ).all()
    return _respond(
        {
            "results": [
                {
                    "document": row.document,
                    "title": row.title,
                    "progress": row.progress,
                    "device": row.device,
                    "time": int(row.updated_at.timestamp()),
                }
                for row in rows
            ]
        }
    )
