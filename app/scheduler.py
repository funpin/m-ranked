from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

import uvicorn

from .collector import Collector
from .config import Settings
from .database import Database
from .public_web import PublicWebCollector
from .telegram_client import TelegramReader
from .web.app import create_app

logger = logging.getLogger(__name__)


async def polling_loop(collector: Collector, settings: Settings) -> None:
    while True:
        try:
            await collector.poll_cycle()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("unhandled polling cycle error")
        await asyncio.sleep(settings.poll_interval_minutes * 60)


async def run_service(settings: Settings, db: Database) -> None:
    if settings.data_source == "public_web":
        collector = PublicWebCollector(settings, db)
        connected = True

        def public_connection_state() -> bool:
            return connected

        app = create_app(settings, db, public_connection_state)
        server = uvicorn.Server(
            uvicorn.Config(app, host=settings.web_host, port=settings.web_port, log_config=None)
        )
        poll_task = asyncio.create_task(polling_loop(collector, settings))
        try:
            await server.serve()
        finally:
            connected = False
            poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await poll_task
            await collector.close()
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
        poll_task = asyncio.create_task(polling_loop(Collector(settings, db, reader), settings))
        await server.serve()
    finally:
        connected = False
        if poll_task:
            poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await poll_task
        await reader.disconnect()
