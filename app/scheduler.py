from __future__ import annotations

import asyncio
import logging
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


def polling_delay_seconds(interval_seconds: float, elapsed_seconds: float) -> float:
    """Keep cycle starts on the configured cadence without overlapping a collector."""
    return max(0.0, interval_seconds - elapsed_seconds)


async def polling_loop(
    collector: Any,
    settings: Settings,
) -> None:
    interval_seconds = settings.poll_interval_minutes * 60
    collector_name = collector.__class__.__name__
    while True:
        loop = asyncio.get_running_loop()
        cycle_started = loop.time()
        try:
            await collector.poll_cycle()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("unhandled %s polling cycle error", collector_name)
        elapsed = loop.time() - cycle_started
        delay = polling_delay_seconds(interval_seconds, elapsed)
        if not delay:
            logger.warning(
                "%s polling cycle exceeded cadence: duration=%.2fs interval=%.2fs",
                collector_name, elapsed, interval_seconds,
            )
        await asyncio.sleep(delay)


def start_polling_tasks(
    collectors: tuple[Any, ...], settings: Settings,
) -> list[asyncio.Task[None]]:
    return [
        asyncio.create_task(
            polling_loop(collector, settings),
            name=f"poll-{collector.__class__.__name__.lower()}",
        )
        for collector in collectors
    ]


async def stop_polling_tasks(tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def run_service(settings: Settings, db: Database) -> None:
    """Run the legacy all-in-one process.

    Production uses ``run_collector_service`` and the CLI ``web`` command as
    independent processes.  Keeping this entry point makes local development
    and older deployments backwards compatible.
    """
    auxiliary_collectors: tuple[Any, ...] = tuple(
        collector for collector in (
            VkCollector(settings, db) if settings.vk_access_token else None,
            MaxCollector(settings, db) if settings.max_user_session_ready else None,
            RutubeCollector(settings, db) if settings.rutube_public_api_enabled else None,
        ) if collector is not None
    )
    if settings.data_source == "public_web":
        collector = PublicWebCollector(settings, db)
        collectors = (collector, *auxiliary_collectors)
        connected = True

        def public_connection_state() -> bool:
            return connected

        app = create_app(settings, db, public_connection_state)
        server = uvicorn.Server(
            uvicorn.Config(app, host=settings.web_host, port=settings.web_port, log_config=None)
        )
        poll_tasks = start_polling_tasks(collectors, settings)
        try:
            await server.serve()
        finally:
            connected = False
            await stop_polling_tasks(poll_tasks)
            for active_collector in collectors:
                await active_collector.close()
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
    poll_tasks: list[asyncio.Task[None]] = []
    try:
        await reader.connect()
        connected = True
        poll_tasks = start_polling_tasks(
            (Collector(settings, db, reader), *auxiliary_collectors), settings,
        )
        await server.serve()
    finally:
        connected = False
        await stop_polling_tasks(poll_tasks)
        await reader.disconnect()
        for auxiliary in auxiliary_collectors:
            await auxiliary.close()


async def run_collector_service(settings: Settings, db: Database) -> None:
    """Run polling independently from the web server until cancelled."""
    auxiliary_collectors: tuple[Any, ...] = tuple(
        collector for collector in (
            VkCollector(settings, db) if settings.vk_access_token else None,
            MaxCollector(settings, db) if settings.max_user_session_ready else None,
            RutubeCollector(settings, db) if settings.rutube_public_api_enabled else None,
        ) if collector is not None
    )
    reader: TelegramReader | None = None
    if settings.data_source == "public_web":
        primary: Any = PublicWebCollector(settings, db)
    else:
        api_id, api_hash = settings.require_telegram()
        reader = TelegramReader(api_id, api_hash, settings.telegram_session_path)
        await reader.connect()
        primary = Collector(settings, db, reader)
    collectors = (primary, *auxiliary_collectors)
    tasks = start_polling_tasks(collectors, settings)
    try:
        await asyncio.Event().wait()
    finally:
        await stop_polling_tasks(tasks)
        if reader is not None:
            await reader.disconnect()
        for active_collector in collectors:
            close = getattr(active_collector, "close", None)
            if callable(close):
                await close()
