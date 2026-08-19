"""Phase 2.1.2 — indexer CRUD API + connectivity test endpoint."""

import respx
from httpx import Response

from libarr.db import session_factory
from libarr.models import Indexer

_CAPS_XML = """<?xml version="1.0"?>
<caps>
  <server title="Prowlarr Test" version="1.0"/>
  <searching><search available="yes" supportedParams="q"/></searching>
  <categories><category id="7000" name="Books"/></categories>
</caps>"""


def _add_indexer(client, **overrides):
    body = {
        "name": "Books",
        "kind": "torznab",
        "url": "http://idx.example",
        "api_key": "k",
        "categories": "7000,7010",
        "priority": 100,
        "enabled": True,
        "rss_enabled": True,
        **overrides,
    }
    return client.post("/api/v1/indexers", json=body)


def test_indexer_create_and_list(client, db):
    client, db = client
    resp = _add_indexer(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Books"
    assert body["kind"] == "torznab"

    listed = client.get("/api/v1/indexers").json()
    assert len(listed) == 1
    assert listed[0]["name"] == "Books"


def test_indexer_create_unknown_kind_rejected(client, db):
    client, _ = client
    resp = _add_indexer(client, kind="bogus")
    assert resp.status_code == 400


def test_indexer_get_update_delete(client, db):
    client, _ = client
    created = _add_indexer(client).json()

    got = client.get(f"/api/v1/indexers/{created['id']}")
    assert got.status_code == 200
    assert got.json()["priority"] == 100

    updated = client.put(
        f"/api/v1/indexers/{created['id']}",
        json={
            "name": "Books2",
            "kind": "torznab",
            "url": "http://new.example",
            "priority": 50,
            "enabled": False,
            "rss_enabled": False,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["priority"] == 50
    assert updated.json()["enabled"] is False

    assert client.delete(f"/api/v1/indexers/{created['id']}").status_code == 200
    assert client.get(f"/api/v1/indexers/{created['id']}").status_code == 404


@respx.mock
def test_indexer_test_endpoint_ok(client, db):
    client, _ = client
    created = _add_indexer(client).json()
    respx.get(url__startswith="http://idx.example/api").mock(
        return_value=Response(200, text=_CAPS_XML)
    )
    resp = client.post(f"/api/v1/indexers/{created['id']}/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["caps"]["title"] == "Prowlarr Test"


@respx.mock
def test_indexer_test_endpoint_failure(client, db):
    client, _ = client
    created = _add_indexer(client).json()
    respx.get(url__startswith="http://idx.example/api").mock(
        return_value=Response(500, text="boom")
    )
    resp = client.post(f"/api/v1/indexers/{created['id']}/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert "error" in resp.json()


def test_legal_indexers_need_no_url(client, db):
    client, db = client
    with session_factory(db)() as session:
        session.add(Indexer(name="PG", kind="gutenberg"))
        session.commit()
    listed = client.get("/api/v1/indexers").json()
    assert any(i["kind"] == "gutenberg" for i in listed)
