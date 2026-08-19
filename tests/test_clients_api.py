"""Phase 2.2 — download client CRUD API + connectivity test."""

import respx
from httpx import Response


def _add_client(client, **overrides):
    body = {
        "name": "qb",
        "kind": "qbittorrent",
        "url": "http://qb:8080",
        "username": "u",
        "password": "p",
        "priority": 100,
        "enabled": True,
        **overrides,
    }
    return client.post("/api/v1/clients", json=body)


def test_client_crud(client, db):
    client, _ = client
    created = _add_client(client)
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["name"] == "qb"
    assert body["kind"] == "qbittorrent"

    listed = client.get("/api/v1/clients").json()
    assert len(listed) == 1

    got = client.get(f"/api/v1/clients/{body['id']}")
    assert got.json()["url"] == "http://qb:8080"

    updated = client.put(
        f"/api/v1/clients/{body['id']}",
        json={"name": "qb2", "kind": "qbittorrent", "url": "http://qb2:8080", "priority": 50},
    )
    assert updated.json()["priority"] == 50

    assert client.delete(f"/api/v1/clients/{body['id']}").status_code == 200
    assert client.get(f"/api/v1/clients/{body['id']}").status_code == 404


def test_client_unknown_kind_rejected(client, db):
    client, _ = client
    resp = _add_client(client, kind="bogus")
    assert resp.status_code == 400


@respx.mock
def test_client_test_endpoint(client, db):
    client, _ = client
    created = _add_client(client).json()
    respx.post("http://qb:8080/api/v2/auth/login").mock(return_value=Response(200, text="Ok."))

    resp = client.post(f"/api/v1/clients/{created['id']}/test")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "error": None}


@respx.mock
def test_client_test_endpoint_failure(client, db):
    client, _ = client
    created = _add_client(client).json()
    respx.post("http://qb:8080/api/v2/auth/login").mock(return_value=Response(200, text="Fails."))

    resp = client.post(f"/api/v1/clients/{created['id']}/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert "error" in resp.json()
