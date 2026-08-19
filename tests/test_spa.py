"""SPA serving: production build at web/dist is routed by the app."""

from fastapi.testclient import TestClient

from libarr import spa
from libarr.main import create_app


def _dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>libarr spa</html>")
    (dist / "assets" / "app.css").write_text("body{}")
    return dist


def test_spa_served_when_dist_exists(tmp_path, monkeypatch):
    dist = _dist(tmp_path)
    monkeypatch.setattr(spa, "SPA_DIST", dist)
    client = TestClient(create_app())

    assert client.get("/").status_code == 200
    assert "libarr spa" in client.get("/").text
    # SPA fallback for client-side routes
    assert "libarr spa" in client.get("/search").text
    # static asset
    asset = client.get("/assets/app.css")
    assert asset.status_code == 200
    assert asset.text == "body{}"
    # API paths are never SPA-routed
    assert client.get("/api/v1/does-not-exist").status_code == 404
    assert client.get("/opds/does-not-exist").status_code == 404


def test_no_spa_without_dist(monkeypatch):
    monkeypatch.setattr(spa, "SPA_DIST", __import__("pathlib").Path("/nonexistent-dist"))
    client = TestClient(create_app())
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/").status_code == 404
