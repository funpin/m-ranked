"""Запуск бота: `python -m telegram_bot`.

Две параллельные задачи: длинный опрос Telegram и тик раз в минуту, который
запускает то, что подошло по расписанию (content.due). Любое исключение внутри
одного обновления или одной задачи пишется в журнал именем класса и не
останавливает цикл: текст ошибки может содержать токен или адрес.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys
from collections.abc import Awaitable
from datetime import datetime
from typing import TypeVar
from zoneinfo import ZoneInfo

from . import alerts_inbox, content
from .config import BotConfig
from .handlers import Bot
from .source import ApiSource, make_client
from .store import PostgresStore
from .telegram import TelegramClient

log = logging.getLogger("telegram_bot")

T = TypeVar("T")

TICK_SECONDS = 60.0
POLL_TIMEOUT_SECONDS = 50
POLL_ERROR_PAUSE_SECONDS = 5.0

# Все имена, которые знает content.due(): по ним читаем время последнего запуска.
JOB_NAMES = ("alerts", "spikes", "anomalies", "week_snapshot", "digest", "morning", "prune")
# Эти задачи сами отмечают запуск через store.set_job_run; планировщик не трогает.
# Остальные ("morning", "prune") он отмечает после успеха; "alerts" не отмечается
# вовсе: разбор очереди идёт на каждом тике, и записывать нечего.


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(stop.wait(), seconds)


async def _until_stop(work: Awaitable[T], stop: asyncio.Event) -> T | None:
    """Результат work, а если раньше сработал stop — None и work отменена."""
    task = asyncio.ensure_future(work)
    waiter = asyncio.ensure_future(stop.wait())
    try:
        await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        waiter.cancel()
        if not task.done():
            task.cancel()  # стоп или отмена снаружи: длинный опрос не оставляем висеть
            # cancel() лишь просит об отмене: результат читается, когда задача
            # действительно завершилась, иначе — InvalidStateError.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
    if task.cancelled():
        return None
    return task.result()


# --- тик ----------------------------------------------------------------------------

async def _run_job(bot: Bot, name: str, now: datetime) -> None:
    if name == "alerts":
        await alerts_inbox.deliver(bot, now)
    elif name == "spikes":
        await content.check_spikes(bot)
    elif name == "anomalies":
        await content.check_anomalies(bot)
    elif name == "week_snapshot":
        await content.record_week(bot)
    elif name == "digest":
        await content.send_digest(bot)
    elif name == "morning":
        await alerts_inbox.morning(bot, now)
        await bot.store.set_job_run(name, bot.clock())
    elif name == "prune":
        await bot.store.prune(bot.clock())
        await bot.store.set_job_run(name, bot.clock())
    else:
        log.warning("неизвестная задача %s", name)


async def tick(bot: Bot) -> None:
    """Один проход: что подошло по расписанию, то выполнить по очереди."""
    try:
        now = datetime.fromtimestamp(bot.clock(), ZoneInfo(bot.config.timezone))
        last = {name: await bot.store.job_last_run(name) for name in JOB_NAMES}
        names = content.due(now, last)
    except Exception as error:  # noqa: BLE001 - тик пропускаем, следующий попробует снова
        log.error("tick: %s", type(error).__name__)
        return
    for name in names:
        try:
            await _run_job(bot, name, now)
        except Exception as error:  # noqa: BLE001 - одна задача не должна останавливать остальные
            log.error("job %s: %s", name, type(error).__name__)


async def _ticker(bot: Bot, stop: asyncio.Event, seconds: float) -> None:
    while not stop.is_set():
        await tick(bot)
        await _sleep_or_stop(stop, seconds)


# --- опрос --------------------------------------------------------------------------

async def _handle(bot: Bot, update: dict) -> None:
    try:
        await bot.handle(update)
    except Exception as error:  # noqa: BLE001 - «ядовитое» обновление не должно крутиться вечно
        log.error("update: %s", type(error).__name__)


async def _poller(bot: Bot, stop: asyncio.Event) -> None:
    offset: int | None = None
    while not stop.is_set():
        try:
            updates = await _until_stop(
                bot.telegram.get_updates(offset, timeout=POLL_TIMEOUT_SECONDS), stop)
        except Exception as error:  # noqa: BLE001 - сеть и Telegram бывают недоступны
            log.error("getUpdates: %s", type(error).__name__)
            await _sleep_or_stop(stop, POLL_ERROR_PAUSE_SECONDS)
            continue
        for update in updates or []:
            update_id = update.get("update_id")
            # Смещение двигаем до разбора: упавшее обновление Telegram больше не пришлёт.
            if isinstance(update_id, int) and (offset is None or update_id >= offset):
                offset = update_id + 1
            await _handle(bot, update)


# --- запуск -------------------------------------------------------------------------

async def _serve(bot: Bot, stop: asyncio.Event, tick_seconds: float) -> None:
    alerts_inbox.install(bot)
    await bot.setup()
    log.info("бот запущен")
    async with asyncio.TaskGroup() as group:
        group.create_task(_poller(bot, stop))
        group.create_task(_ticker(bot, stop, tick_seconds))
    log.info("бот остановлен")


async def run(config: BotConfig, *, stop: asyncio.Event, bot: Bot | None = None,
              tick_seconds: float = TICK_SECONDS) -> None:
    """`bot` нужен только тестам: в проде всё собирается из config."""
    if bot is not None:
        await _serve(bot, stop, tick_seconds)
        return
    async with (
        TelegramClient(config.token) as telegram,
        make_client(config.api_base_url) as client,
        PostgresStore(config.dsn) as store,
    ):
        await _serve(Bot(telegram, ApiSource(client), store, config), stop, tick_seconds)


async def _run_until_signal(config: BotConfig) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    await run(config, stop=stop)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    # Адрес запроса к Telegram содержит токен: httpx на INFO печатает каждый запрос.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        config = BotConfig.from_env(os.environ)
    except SystemExit as error:
        log.error("%s", error.code)
        return 2
    try:
        asyncio.run(_run_until_signal(config))
    except Exception as error:  # noqa: BLE001 - причину в журнал, systemd перезапустит
        log.error("бот остановился: %s", type(error).__name__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
