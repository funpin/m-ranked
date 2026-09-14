"""Сборка приложения."""
from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from .cache import InvalidationListener, ResponseCache
from .config import Settings
from .db import Database
from .errors import ApiProblem, handle, handle_validation
from .export_jobs import ExportJobs
from .outbox import OutboxMarker
from .security import AuthConfig
from .routes import admin, analysis, compare, emoji, exports, health, query, rating

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    database = Database(settings)
    cache = ResponseCache(settings.cache_entries, settings.cache_ttl_seconds,
                          settings.cache_min_age_seconds)
    export_jobs = ExportJobs(database)
    listener = InvalidationListener(settings.read_dsn, cache) if settings.read_dsn else None
    outbox = OutboxMarker(settings.outbox_dsn) if settings.outbox_dsn else None

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await database.open()
        await export_jobs.start()
        if listener is not None:
            await listener.start()
        if outbox is not None:
            await outbox.start()
        try:
            yield
        finally:
            if listener is not None:
                await listener.stop()
            if outbox is not None:
                await outbox.stop()
            await export_jobs.close()
            await database.close()

    app = FastAPI(
        title="M-Ranked API",
        version="1.0.0",
        lifespan=lifespan,
        # Контракт — contracts/openapi/m-ranked-v1.yaml, он и есть источник
        # истины. Схему, которую FastAPI сочинил бы сам, не публикуем.
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.db = database
    app.state.cache = cache
    app.state.auth = AuthConfig.from_environment()
    app.state.export_jobs = export_jobs
    app.add_exception_handler(ApiProblem, handle)
    app.add_exception_handler(RequestValidationError, handle_validation)

    for module in (health, query, rating, compare, emoji, exports, analysis, admin):
        app.include_router(module.router)
    return app
