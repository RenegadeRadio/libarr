"""Phase 0.3 — health endpoint exposes app identity and liveness."""

from fastapi.testclient import TestClient

from libarr.main import app


def test_health_returns_ok_with_version():
    client = TestClient(app)

    resp = client.get("/api/v1/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"


def test_health_path_is_under_api_v1():
    client = TestClient(app)

    resp = client.get("/api/v1/health")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
