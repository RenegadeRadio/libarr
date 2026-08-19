"""FastAPI application factory for Libarr."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from libarr import __version__
from libarr.api.auth import router as auth_router
from libarr.api.routes import opds_router
from libarr.api.routes import router as api_router
from libarr.config import Settings
from libarr.db import make_engine
from libarr.scheduler import scheduler_loop


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    engine = make_engine(settings.database_url)
    task: asyncio.Task[None] | None = None
    if settings.scheduler_enabled:
        task = asyncio.create_task(
            scheduler_loop(
                engine,
                interval_seconds=float(settings.scheduler_interval_seconds),
                jitter_seconds=float(settings.scheduler_jitter_seconds),
            )
        )
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Libarr", version=__version__, lifespan=lifespan)
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(opds_router)  # OPDS lives at the root for e-readers
    app.include_router(auth_router, prefix="/api/v1")

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
