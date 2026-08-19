"""OIDC single sign-on (Phase 4): authorization-code flow with userinfo.

Verification model: the code is exchanged for an access token over TLS and
the user's identity is taken from the IdP's userinfo endpoint (the standard
code-flow pattern). The id_token's signature is not verified locally (JWKS
parity is a future pass) — userinfo over TLS is the trust anchor, matching
how many self-hosted tools integrate OIDC.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import cast
from urllib.parse import urlencode

import httpx

from libarr.config import Settings


class OidcError(Exception):
    pass


def _discovery(issuer: str) -> dict[str, str]:
    try:
        resp = httpx.get(
            f"{issuer.rstrip('/')}/.well-known/openid-configuration",
            timeout=15,
            follow_redirects=True,
        )
        resp.raise_for_status()
        payload = resp.json()
        return cast("dict[str, str]", payload)
    except (httpx.HTTPError, ValueError) as exc:
        raise OidcError(f"OIDC discovery failed: {exc}") from exc


def make_state(secret: str) -> tuple[str, str]:
    """Return (state, signed_token) — the signed token rides the callback URL."""
    nonce = secrets.token_urlsafe(24)
    digest = hmac.new(secret.encode(), nonce.encode(), hashlib.sha256).digest()
    return nonce, nonce + "." + base64.urlsafe_b64encode(digest).decode().rstrip("=")


def verify_state(secret: str, token: str) -> bool:
    try:
        nonce, _, sig = token.partition(".")
        expected = hmac.new(secret.encode(), nonce.encode(), hashlib.sha256).digest()
        given = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
        return hmac.compare_digest(expected, given)
    except (ValueError, TypeError):
        return False


def build_authorize_url(settings: Settings, callback_url: str) -> tuple[str, str]:
    if not settings.oidc_issuer:
        raise OidcError("OIDC is not configured (LIBARR_OIDC_ISSUER)")
    meta = _discovery(settings.oidc_issuer)
    state, signed = make_state(settings.oidc_client_secret or "libarr")
    params = urlencode(
        {
            "response_type": "code",
            "client_id": settings.oidc_client_id,
            "redirect_uri": callback_url,
            "scope": "openid email profile",
            "state": signed,
        }
    )
    return f"{meta['authorization_endpoint']}?{params}", state


def exchange_and_userinfo(settings: Settings, callback_url: str, code: str) -> dict[str, object]:
    meta = _discovery(settings.oidc_issuer)
    try:
        token_resp = httpx.post(
            meta["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": callback_url,
                "client_id": settings.oidc_client_id,
                "client_secret": settings.oidc_client_secret,
            },
            timeout=15,
        )
        token_resp.raise_for_status()
        token = token_resp.json()
        userinfo_resp = httpx.get(
            meta["userinfo_endpoint"],
            headers={"Authorization": f"Bearer {token['access_token']}"},
            timeout=15,
        )
        userinfo_resp.raise_for_status()
        payload = userinfo_resp.json()
        return cast("dict[str, object]", payload)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise OidcError(f"OIDC token/userinfo exchange failed: {exc}") from exc
