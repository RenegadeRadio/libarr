"""Phase 1.11 — auth: bootstrap admin, login/logout, API keys, forced auth."""


def test_bootstrap_status_needed(raw_client):
    assert raw_client.get("/api/v1/auth/bootstrap").json() == {"needed": True}


def test_bootstrap_creates_admin_and_can_login(raw_client):
    resp = raw_client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": "hunter2!"},
    )
    assert resp.status_code == 200
    user = resp.json()
    assert user["username"] == "admin"
    assert user["role"] == "admin"
    assert user["api_key"]  # generated for integrations

    assert raw_client.get("/api/v1/auth/bootstrap").json() == {"needed": False}

    # Second bootstrap attempt is refused.
    resp = raw_client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "other", "password": "whatever"},
    )
    assert resp.status_code == 409


def test_login_wrong_password_rejected(raw_client):
    raw_client.post("/api/v1/auth/bootstrap", json={"username": "admin", "password": "hunter2!"})

    resp = raw_client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "wrong"}
    )
    assert resp.status_code == 401


def test_forced_auth_blocks_anonymous_api(raw_client):
    raw_client.post("/api/v1/auth/bootstrap", json={"username": "admin", "password": "hunter2!"})

    assert raw_client.get("/api/v1/books").status_code == 401
    assert raw_client.get("/api/v1/authors").status_code == 401
    assert raw_client.get("/opds").status_code == 401
    # Health stays public for liveness probes.
    assert raw_client.get("/api/v1/health").status_code == 200


def test_login_sets_session_cookie_and_me_works(raw_client):
    raw_client.post("/api/v1/auth/bootstrap", json={"username": "admin", "password": "hunter2!"})
    raw_client.post("/api/v1/auth/login", json={"username": "admin", "password": "hunter2!"})

    me = raw_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "admin"

    # Session cookie is how the API client authenticates.
    assert "libarr_session" in raw_client.cookies


def test_api_key_authenticates(raw_client):
    raw_client.post("/api/v1/auth/bootstrap", json={"username": "admin", "password": "hunter2!"})
    raw_client.post("/api/v1/auth/login", json={"username": "admin", "password": "hunter2!"})
    api_key = raw_client.get("/api/v1/auth/me").json()["api_key"]

    resp = raw_client.get("/api/v1/books", headers={"X-Api-Key": api_key})
    assert resp.status_code == 200

    # A bogus key must fail even though the session cookie is still valid —
    # clear the cookie to prove the key alone is rejected.
    raw_client.cookies.clear()
    resp = raw_client.get("/api/v1/books", headers={"X-Api-Key": "bogus"})
    assert resp.status_code == 401


def test_basic_auth_works_for_opds(raw_client):
    raw_client.post("/api/v1/auth/bootstrap", json={"username": "admin", "password": "hunter2!"})

    resp = raw_client.get("/opds", auth=("admin", "hunter2!"))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/atom+xml")


def test_logout_clears_session(raw_client):
    raw_client.post("/api/v1/auth/bootstrap", json={"username": "admin", "password": "hunter2!"})
    raw_client.post("/api/v1/auth/login", json={"username": "admin", "password": "hunter2!"})

    assert raw_client.get("/api/v1/auth/me").status_code == 200
    raw_client.post("/api/v1/auth/logout")
    assert raw_client.get("/api/v1/auth/me").status_code == 401
