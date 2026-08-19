"""SPA serving (production): the built Vue app lives in web/dist."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

# The built frontend. Replaced by tests to exercise the fallback logic.
SPA_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"

# Path prefixes owned by the API/OPDS/KOReader routers — never SPA-routed.
_API_PREFIXES = ("api/", "opds", "koreader/")


def mount_spa(app: FastAPI) -> None:
    """Serve the SPA from disk when a production build exists (no-op in dev)."""
    dist = SPA_DIST.resolve()
    if not (dist / "index.html").is_file():
        return

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa_fallback(path: str) -> Response:
        if path.startswith(_API_PREFIXES):
            raise HTTPException(status_code=404)
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist):
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")
