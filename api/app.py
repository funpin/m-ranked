"""Сборка приложения."""
from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from .cache import InvalidationListener, ResponseCache
from .config import Settings
from .db import Database
from .errors import ApiProblem, handle, handle_validation
from .export_jobs import ExportJobs
from .limits import BodyLimit
from .outbox import OutboxMarker
from .security import AuthConfig
from .security_events import SecurityTelemetry
from .sessions import SessionPolicy, SessionStore
from .routes import admin, analysis, compare, emoji, exports, health, query, statistics

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    database = Database(settings)
    cache = ResponseCache(settings.cache_entries, settings.cache_ttl_seconds,
                          settings.cache_min_age_seconds,
                          settings.cache_stale_seconds)
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
    # Неверная настройка админки закрывает админку, а не весь API: публичное
    # чтение к учётным записям отношения не имеет, и ронять из-за них сайт
    # целиком — менять одну неприятность на другую, большую.
    try:
        app.state.auth = AuthConfig.from_environment()
    except ValueError as error:
        logger.error("административный интерфейс отключён: %s", error)
        app.state.auth = AuthConfig.disabled(str(error))
    app.state.security = SecurityTelemetry.from_environment()
    try:
        app.state.session_policy = SessionPolicy.from_environment()
    except ValueError as error:
        logger.error("административные сессии отключены: %s", error)
        app.state.auth = AuthConfig.disabled(str(error))
        app.state.session_policy = SessionPolicy()
    # Единственные часы приложения: тест подменяет их и получает
    # воспроизводимые шаги TOTP и сроки сессии.
    app.state.clock = time.time
    app.state.sessions = SessionStore(database, app.state.session_policy,
                                      lambda: app.state.clock())
    app.state.export_jobs = export_jobs
    app.add_exception_handler(ApiProblem, handle)
    app.add_exception_handler(RequestValidationError, handle_validation)

    for module in (health, query, statistics, compare, emoji, exports, analysis, admin):
        app.include_router(module.router)
    app.add_middleware(BodyLimit, maximum=settings.max_body_bytes)
    return app
