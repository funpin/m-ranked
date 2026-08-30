from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

import uvicorn

from .collector import Collector
from .config import Settings
from .database import Database
from .max_collector import MaxCollector
from .public_web import PublicWebCollector
from .rutube_collector import RutubeCollector
from .telegram_client import TelegramReader
from .vk_collector import VkCollector
from .web.app import create_app

logger = logging.getLogger(__name__)


async def polling_loop(
    collector: Any,
    settings: Settings,
    auxiliary_collectors: tuple[Any, ...] = (),
) -> None:
    while True:
        try:
            await collector.poll_cycle()
            for auxiliary in auxiliary_collectors:
                await auxiliary.poll_cycle()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("unhandled polling cycle error")
        await asyncio.sleep(settings.poll_interval_minutes * 60)


async def run_service(settings: Settings, db: Database) -> None:
    auxiliary_collectors: tuple[Any, ...] = tuple(
        collector for collector in (
            VkCollector(settings, db) if settings.vk_access_token else None,
            MaxCollector(settings, db) if settings.max_access_token else None,
            RutubeCollector(settings, db) if settings.rutube_public_api_enabled else None,
        ) if collector is not None
    )
    if settings.data_source == "public_web":
        collector = PublicWebCollector(settings, db)
        connected = True

        def public_connection_state() -> bool:
            return connected

        app = create_app(settings, db, public_connection_state)
        server = uvicorn.Server(
            uvicorn.Config(app, host=settings.web_host, port=settings.web_port, log_config=None)
        )
        poll_task = asyncio.create_task(
            polling_loop(collector, settings, auxiliary_collectors)
        )
        try:
            await server.serve()
        finally:
            connected = False
            poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await poll_task
            await collector.close()
            for auxiliary in auxiliary_collectors:
                await auxiliary.close()
        return

    api_id, api_hash = settings.require_telegram()
    reader = TelegramReader(api_id, api_hash, settings.telegram_session_path)
    connected = False

    def connection_state() -> bool:
        return connected and bool(reader.client.is_connected())

    app = create_app(settings, db, connection_state)
    server = uvicorn.Server(
        uvicorn.Config(app, host=settings.web_host, port=settings.web_port, log_config=None)
    )
    poll_task: asyncio.Task[None] | None = None
    try:
        await reader.connect()
        connected = True
        poll_task = asyncio.create_task(
            polling_loop(Collector(settings, db, reader), settings, auxiliary_collectors)
        )
        await server.serve()
    finally:
        connected = False
        if poll_task:
            poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await poll_task
        await reader.disconnect()
        for auxiliary in auxiliary_collectors:
            await auxiliary.close()
