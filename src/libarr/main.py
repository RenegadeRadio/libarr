"""FastAPI application factory for Libarr."""

from fastapi import FastAPI

from libarr import __version__
from libarr.api.auth import router as auth_router
from libarr.api.routes import opds_router
from libarr.api.routes import router as api_router


def create_app() -> FastAPI:
    app = FastAPI(title="Libarr", version=__version__)
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(opds_router)  # OPDS lives at the root for e-readers
    app.include_router(auth_router, prefix="/api/v1")

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
