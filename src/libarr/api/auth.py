"""Authentication (plan Task 1.11): forced login, bootstrap admin, API keys.

Three credential paths, in priority order:
1. Signed session cookie (the SPA).
2. X-Api-Key header (scripts, integrations).
3. HTTP Basic (OPDS e-readers — KOReader/Kobo support basic auth).

`auth_enabled=false` (LIBARR_AUTH_ENABLED) disables the wall for LAN-first
deployments, mirroring *Arr v4's forced-auth posture in reverse.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import APIKeyHeader, HTTPBasic, HTTPBasicCredentials
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pwdlib import PasswordHash
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from libarr.api.deps import get_session
from libarr.api.schemas import BootstrapBody, BootstrapStatus, LoginBody, UserOut
from libarr.config import Settings
from libarr.models import User

router = APIRouter()

_password_hash = PasswordHash.recommended()
_basic = HTTPBasic(auto_error=False)
_api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)

COOKIE_NAME = "libarr_session"
SESSION_TTL = timedelta(days=30)
_FALLBACK_SECRET = "libarr-insecure-dev-secret"


def _secret() -> str:
    return Settings().secret_key or _FALLBACK_SECRET


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(), salt="libarr-session")


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        # pwdlib's API is verify(password, hash) — password comes first.
        return _password_hash.verify(password, password_hash)
    except Exception:  # noqa: BLE001 — malformed hash must read as "no match"
        return False


def issue_api_key() -> str:
    return secrets.token_urlsafe(32)


def create_session_token(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def read_session_token(token: str) -> int | None:
    try:
        data = _serializer().loads(
            token, max_age=int(SESSION_TTL.total_seconds())
        )
    except (BadSignature, SignatureExpired):
        return None
    uid = data.get("uid")
    return uid if isinstance(uid, int) else None


def get_current_user(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    basic: Annotated[HTTPBasicCredentials | None, Depends(_basic)],
    api_key: Annotated[str | None, Depends(_api_key_header)],
) -> User | None:
    """Resolve the authenticated user from cookie / API key / basic auth."""
    token = request.cookies.get(COOKIE_NAME)
    if token:
        uid = read_session_token(token)
        if uid is not None:
            user = session.get(User, uid)
            if user is not None:
                return user

    if api_key:
        user = session.scalars(select(User).where(User.api_key == api_key)).first()
        if user is not None:
            return user

    if basic is not None:
        user = session.scalars(
            select(User).where(User.username == basic.username)
        ).first()
        if user is not None and verify_password(basic.password, user.password_hash):
            return user
    return None


def require_user(user: Annotated[User | None, Depends(get_current_user)]) -> User:
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )
    return user


def require_admin(user: Annotated[User, Depends(require_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


def _user_out(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "api_key": user.api_key,
    }


@router.get("/auth/bootstrap", response_model=BootstrapStatus)
def bootstrap_status(session: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    count = session.scalar(select(func.count()).select_from(User))
    return {"needed": count == 0}


@router.post("/auth/bootstrap", response_model=UserOut)
def bootstrap(
    body: BootstrapBody, session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    count = session.scalar(select(func.count()).select_from(User))
    if count and count > 0:
        raise HTTPException(status_code=409, detail="Bootstrap already completed")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role="admin",
        api_key=issue_api_key(),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return _user_out(user)


@router.post("/auth/login")
def login(
    body: LoginBody,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    user = session.scalars(
        select(User).where(User.username == body.username)
    ).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_session_token(user.id)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
    )
    return {"status": "ok"}


@router.post("/auth/logout")
def logout(response: Response) -> dict[str, Any]:
    response.delete_cookie(COOKIE_NAME)
    return {"status": "ok"}


@router.get("/auth/me", response_model=UserOut)
def me(user: Annotated[User, Depends(require_user)]) -> dict[str, Any]:
    return _user_out(user)
