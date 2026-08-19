"""SPA serving (production): the built Vue app lives in web/dist."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

# Path prefixes owned by the API/OPDS/KOReader routers — never SPA-routed.
_API_PREFIXES = ("api/", "opds", "koreader/")


def _find_dist() -> Path:
    """Locate the built frontend.

    Explicit env wins (Docker sets LIBARR_SPA_DIST=/app/web/dist). Otherwise
    look next to the source tree (editable install) then at the image path
    (non-editable install puts libarr in site-packages).
    """
    env = os.environ.get("LIBARR_SPA_DIST")
    if env:
        return Path(env)
    source_tree = Path(__file__).resolve().parents[2] / "web" / "dist"
    if (source_tree / "index.html").is_file():
        return source_tree
    image_path = Path("/app/web/dist")
    if (image_path / "index.html").is_file():
        return image_path
    return source_tree


SPA_DIST = _find_dist()


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
