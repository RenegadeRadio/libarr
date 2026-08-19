"""Phase 4 — OIDC single sign-on + modular worker split."""

import respx
from httpx import Response
from sqlalchemy import select

from libarr.api.auth import COOKIE_NAME
from libarr.db import session_factory
from libarr.models import User

ISSUER = "https://idp.example.com"
DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "userinfo_endpoint": f"{ISSUER}/userinfo",
    "jwks_uri": f"{ISSUER}/jwks",
}


def _enable_oidc(monkeypatch, *, issuer=ISSUER, client_id="libarr", secret="s3cret"):
    monkeypatch.setenv("LIBARR_OIDC_ISSUER", issuer)
    monkeypatch.setenv("LIBARR_OIDC_CLIENT_ID", client_id)
    monkeypatch.setenv("LIBARR_OIDC_CLIENT_SECRET", secret)
    from libarr.config import Settings

    s = Settings()
    assert s.oidc_issuer == issuer


# --- login flow -----------------------------------------------------------------


def test_oidc_disabled_returns_400(client, db, monkeypatch):
    client, db = client
    monkeypatch.delenv("LIBARR_OIDC_ISSUER", raising=False)
    resp = client.get("/api/v1/auth/oidc/login")
    assert resp.status_code == 400


@respx.mock
def test_oidc_login_redirects_to_idp(client, db, monkeypatch):
    client, db = client
    _enable_oidc(monkeypatch)
    respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(
        return_value=Response(200, json=DISCOVERY)
    )

    resp = client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith(f"{ISSUER}/authorize?")
    assert "client_id=libarr" in location
    assert "state=" in location
    assert "redirect_uri=" in location


@respx.mock
def test_oidc_callback_provisions_user_and_logs_in(client, db, monkeypatch):
    client, db = client
    _enable_oidc(monkeypatch)
    respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(
        return_value=Response(200, json=DISCOVERY)
    )
    respx.post(f"{ISSUER}/token").mock(
        return_value=Response(
            200,
            json={"access_token": "at1", "token_type": "Bearer"},
            headers={"Content-Type": "application/json"},
        )
    )
    respx.get(f"{ISSUER}/userinfo").mock(
        return_value=Response(
            200, json={"sub": "user-123", "email": "oidc@example.com", "name": "OIDC User"}
        )
    )

    # Get the state from the login redirect
    login = client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    state = _extract_param(login.headers["location"], "state")

    resp = client.get(
        f"/api/v1/auth/oidc/callback?code=abc123&state={state}", follow_redirects=False
    )
    assert resp.status_code == 302
    assert "set-cookie" in resp.headers
    assert COOKIE_NAME in resp.headers["set-cookie"]

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "oidc@example.com"

    with session_factory(db)() as session:
        user = session.scalars(select(User).where(User.username == "oidc@example.com")).first()
        assert user is not None
        assert user.oidc_sub == "user-123"


@respx.mock
def test_oidc_callback_reuses_existing_user(client, db, monkeypatch):
    client, db = client
    _enable_oidc(monkeypatch)
    from libarr.api.auth import hash_password

    with session_factory(db)() as session:
        session.add(
            User(
                username="oidc@example.com",
                password_hash=hash_password("unused"),
                role="user",
                oidc_sub="user-123",
            )
        )
        session.commit()

    respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(
        return_value=Response(200, json=DISCOVERY)
    )
    respx.post(f"{ISSUER}/token").mock(
        return_value=Response(200, json={"access_token": "at1", "token_type": "Bearer"})
    )
    respx.get(f"{ISSUER}/userinfo").mock(
        return_value=Response(200, json={"sub": "user-123", "email": "oidc@example.com"})
    )

    login = client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    state = _extract_param(login.headers["location"], "state")
    resp = client.get(f"/api/v1/auth/oidc/callback?code=abc&state={state}", follow_redirects=False)
    assert resp.status_code == 302

    with session_factory(db)() as session:
        users = session.scalars(select(User)).all()
        assert len(users) == 2  # admin + the oidc user, no duplicate


@respx.mock
def test_oidc_callback_rejects_bad_state(client, db, monkeypatch):
    client, db = client
    _enable_oidc(monkeypatch)
    resp = client.get("/api/v1/auth/oidc/callback?code=abc&state=tampered")
    assert resp.status_code == 400


# --- worker split ----------------------------------------------------------------


def test_worker_once_runs_a_cycle(client, db, monkeypatch):
    client, db = client
    import libarr.cli as cli

    calls = {"n": 0}

    def _run(engine):
        calls["n"] += 1

    monkeypatch.setattr(cli, "run_cycles", _run)

    code = cli.main(["worker", "--once"])
    assert code == 0
    assert calls["n"] == 1


def _extract_param(url: str, name: str) -> str:
    from urllib.parse import parse_qs, urlparse

    return parse_qs(urlparse(url).query)[name][0]
