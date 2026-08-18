"""FastAPI application factory for Libarr."""

from fastapi import FastAPI

from libarr import __version__


def create_app() -> FastAPI:
    app = FastAPI(title="Libarr", version=__version__)

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
