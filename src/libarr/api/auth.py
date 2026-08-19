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
from fastapi.responses import RedirectResponse
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
        data = _serializer().loads(token, max_age=int(SESSION_TTL.total_seconds()))
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
        user = session.scalars(select(User).where(User.username == basic.username)).first()
        if user is not None and verify_password(basic.password, user.password_hash):
            return user
    return None


def require_user(user: Annotated[User | None, Depends(get_current_user)]) -> User:
    if user is None:
        # NOTE: no WWW-Authenticate header here — Chromium hangs same-origin
        # fetches on 401+Basic challenges (headless proved it). OPDS clients
        # retry with Basic credentials on a bare 401 just fine.
        raise HTTPException(status_code=401, detail="Authentication required")
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
    user = session.scalars(select(User).where(User.username == body.username)).first()
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


@router.get("/auth/oidc/login")
def oidc_login(
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
) -> RedirectResponse:
    """Start the OIDC authorization-code flow (redirects to the IdP)."""
    from libarr.oidc import OidcError, build_authorize_url

    settings = Settings()
    callback_url = str(request.base_url).rstrip("/") + "/api/v1/auth/oidc/callback"
    try:
        authorize_url, state = build_authorize_url(settings, callback_url)
    except OidcError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # The unsigned state rides a cookie so the callback can verify the flow
    # started here (the URL carries the HMAC-signed twin). The cookie must go
    # on the returned redirect, not the injected response (which is discarded).
    redirect = RedirectResponse(authorize_url, status_code=302)
    redirect.set_cookie("oidc_state", state, httponly=True, max_age=600)
    return redirect


@router.get("/auth/oidc/callback")
def oidc_callback(
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    code: str = "",
    state: str = "",
) -> RedirectResponse:
    """Complete the flow: exchange code → userinfo → issue a Libarr session."""
    from libarr.oidc import OidcError, exchange_and_userinfo, verify_state

    settings = Settings()
    expected = request.cookies.get("oidc_state")
    if not expected or not verify_state(settings.oidc_client_secret or "libarr", state):
        raise HTTPException(status_code=400, detail="Invalid OIDC state")
    callback_url = str(request.base_url).rstrip("/") + "/api/v1/auth/oidc/callback"
    try:
        info = exchange_and_userinfo(settings, callback_url, code)
    except OidcError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sub = str(info.get("sub") or "")
    if not sub:
        raise HTTPException(status_code=400, detail="OIDC userinfo missing 'sub'")
    email = str(info.get("email") or f"oidc-{sub}")
    user = session.scalars(select(User).where(User.oidc_sub == sub)).first()
    if user is None:
        user = session.scalars(select(User).where(User.username == email)).first()
    if user is None:
        user = User(
            username=email,
            password_hash=hash_password(
                secrets.token_urlsafe(24)
            ),  # OIDC users never log in with a password
            role="user",
            oidc_sub=sub,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
    token = create_session_token(user.id)
    redirect = RedirectResponse("/", status_code=302)
    redirect.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        max_age=int(SESSION_TTL.total_seconds()),
        samesite="lax",
    )
    redirect.delete_cookie("oidc_state")
    return redirect


@router.post("/auth/logout")
def logout(response: Response) -> dict[str, Any]:
    response.delete_cookie(COOKIE_NAME)
    return {"status": "ok"}


@router.get("/auth/me", response_model=UserOut)
def me(user: Annotated[User, Depends(require_user)]) -> dict[str, Any]:
    return _user_out(user)
