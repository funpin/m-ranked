"""Тревоги сервера: очередь файлов → люди из списка тревог.

Скрипт тревог (operations/scripts/alerts.py) кладёт по файлу на каждый переход
в каталог очереди. Здесь они читаются по имени (то есть по времени), глушатся
по ключу, ночью несрочные откладываются до утренней сводки, остальные уходят
людям с флагом «тревоги». В журнал попадают только имена файлов и классы
ошибок: ни текстов тревог, ни Telegram ID.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .access import Access
from .handlers import STALE_BUTTON, Bot
from .render import Message, esc
from .store import Recipient

log = logging.getLogger(__name__)

MOSCOW = ZoneInfo("Europe/Moscow")
QUIET_FROM_HOUR = 23
QUIET_TO_HOUR = 8
MUTE_SECONDS = 2 * 3600
STALE_TEMPORARY_SECONDS = 3600
# Равно интервалу «повтора» в alerts.py: открытая тревога всё равно объявится заново.
STALE_SECONDS = 6 * 3600
# Дольше суток утреннюю сводку не донести: события из неё больше не возвращаем.
HELD_MAX_SECONDS = 24 * 3600
CALLBACK_LIMIT = 64
SPOOL_VERSION = 1
KINDS = ("open", "repeat", "resolve")
MUTE_BUTTON = "🔕 Заглушить на 2 часа"
MUTED_NOTE = "заглушено на 2 часа"


# --- очередь ---------------------------------------------------------------------

def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _valid(event: object) -> bool:
    return (
        isinstance(event, dict)
        and event.get("version") == SPOOL_VERSION
        and isinstance(event.get("server"), str)
        and isinstance(event.get("key"), str) and bool(event["key"])
        and event.get("kind") in KINDS
        and isinstance(event.get("text"), str)
        # Без числового «at» возраст не посчитать, и такой файл застрял бы в голове очереди.
        and _number(event.get("at"))
    )


def _discard(path: Path, reason: str) -> None:
    log.warning("alert spool: %s dropped (%s)", path.name, reason)
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        log.warning("alert spool: %s not removed (%s)", path.name, type(error).__name__)


def read_inbox(spool: Path, now: float | None = None) -> list[tuple[Path, dict]]:
    """События очереди по имени файла (имя начинается со времени записи).

    Точечные файлы и *.tmp — недописанное, их пропускаем; забытые старше часа
    убираем. Файл с неверным JSON или версией удаляем, в журнале — только класс."""
    now = time.time() if now is None else now
    try:
        entries = sorted(spool.iterdir(), key=lambda path: path.name)
    except OSError as error:
        if not isinstance(error, FileNotFoundError):
            log.warning("alert spool: not readable (%s)", type(error).__name__)
        return []
    events: list[tuple[Path, dict]] = []
    for path in entries:
        name = path.name
        if name.startswith("."):
            if name.endswith(".tmp"):
                try:
                    if now - path.stat().st_mtime > STALE_TEMPORARY_SECONDS:
                        path.unlink(missing_ok=True)
                except OSError:
                    pass
            continue
        if not name.endswith(".json"):
            continue
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, RecursionError) as error:  # JSONDecodeError и UnicodeDecodeError — ValueError
            _discard(path, type(error).__name__)
            continue
        except OSError as error:
            log.warning("alert spool: %s not read (%s)", name, type(error).__name__)
            continue
        if not _valid(event):
            _discard(path, "format")
            continue
        events.append((path, event))
    return events


# --- текст -------------------------------------------------------------------------

def _since(event: dict) -> str:
    since = event.get("since")
    if isinstance(since, bool) or not isinstance(since, (int, float)):
        since = event.get("at")
    if isinstance(since, bool) or not isinstance(since, (int, float)):
        return "?"
    return datetime.fromtimestamp(since, MOSCOW).strftime("%d.%m %H:%M")


def _line(event: dict) -> str:
    """Строка в формате format_event из скрипта тревог (текст экранирован под HTML)."""
    text = esc(event["text"])
    if event["kind"] == "open":
        return f"🔴 {text}"
    if event["kind"] == "repeat":
        return f"🔴 Всё ещё: {text} (с {_since(event)})"
    return f"🟢 Прошло: {text}"


def alert_text(event: dict) -> str:
    return f"m-ranked · {esc(event['server'])}\n{_line(event)}"


def _keyboard(event: dict) -> list[list[dict]] | None:
    """Кнопка заглушки — под открытием и повтором; ключ не влезает в 64 байта — без кнопки."""
    if event["kind"] == "resolve":
        return None
    data = f"m|{event['key']}"
    if len(data.encode()) > CALLBACK_LIMIT:
        return None
    return [[{"text": MUTE_BUTTON, "callback_data": data}]]


# --- тихие часы ---------------------------------------------------------------------

def is_quiet(now: datetime) -> bool:
    """23:00–08:00 по Москве; без часового пояса время считается московским."""
    moment = now.astimezone(MOSCOW) if now.tzinfo is not None else now
    return moment.hour >= QUIET_FROM_HOUR or moment.hour < QUIET_TO_HOUR


# --- доставка -------------------------------------------------------------------------

def _age(event: dict, now: float) -> float:
    return now - event["at"]


def _require_aware(now: datetime, caller: str) -> None:
    if now.tzinfo is None:
        raise ValueError(f"{caller}(): now должен быть с часовым поясом (Europe/Moscow)")


def _alert_people(recipients: list[Recipient]) -> list[Recipient]:
    return [r for r in recipients if r.kind == "person" and r.alerts]


async def deliver(bot: Bot, now: datetime) -> None:
    """Разобрать очередь. Файл остаётся, только если получатели есть, а не дошло никому.
    `now` обязан быть с часовым поясом; возраст событий считается от now.timestamp()."""
    _require_aware(now, "deliver")
    inbox = read_inbox(bot.config.spool_dir)
    if not inbox:
        return
    has_people = bool(_alert_people(await bot.store.recipients()))
    quiet = is_quiet(now)
    moment = now.timestamp()
    for path, event in inbox:
        if not has_people:
            path.unlink(missing_ok=True)
            continue
        if _age(event, moment) > STALE_SECONDS:
            # Недоставимая очередь не должна копиться вечно и потом хлынуть потоком.
            log.warning("alert spool: %s stale, dropped", path.name)
            path.unlink(missing_ok=True)
            continue
        # Заглушка ключуется одним ключом правила: alerts.py работает только на Сервере 2,
        # правила Сервера 1 имеют приставку node_<id>_, пересечений нет.
        if event["kind"] != "resolve" and await bot.store.muted_until(event["key"]) is not None:
            path.unlink(missing_ok=True)
            continue
        if quiet and not event.get("urgent"):
            await bot.store.hold_alert(event)
            path.unlink(missing_ok=True)
            continue
        if await bot.broadcast(Message(alert_text(event), _keyboard(event)), "alerts") == 0:
            # Порядок событий важен: до следующего тика дальше не идём.
            log.warning("alert spool: %s not delivered, kept for the next tick", path.name)
            return
        path.unlink(missing_ok=True)


async def morning(bot: Bot, now: datetime) -> None:
    """Одно сообщение про всё, что копилось ночью. Не дошло — события возвращаются.
    `now` обязан быть с часовым поясом."""
    _require_aware(now, "morning")
    held = await bot.store.take_held()
    if not held:
        return
    if not _alert_people(await bot.store.recipients()):
        return
    lines = [_summary_line(group) for group in _by_key(held)]
    text = "Тревоги за ночь\n" + "\n".join(lines)
    if await bot.broadcast(text, "alerts") == 0:
        moment = now.timestamp()
        for event in held:
            if _age(event, moment) <= HELD_MAX_SECONDS:
                await bot.store.hold_alert(event)


def _by_key(held: list[dict]) -> list[list[dict]]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for event in held:
        groups.setdefault((event["server"], event["key"]), []).append(event)
    return list(groups.values())


def _summary_line(group: list[dict]) -> str:
    last = group[-1]
    server = esc(last["server"])
    if last["kind"] == "resolve":
        opened = [e for e in group if e["kind"] in ("open", "repeat")]
        if opened:
            return f"• {server}: за ночь открылась и закрылась: {esc(opened[0]['text'])}"
    return f"• {server}: {_line(last)}"


# --- кнопка «заглушить» ------------------------------------------------------------------

async def on_mute(bot: Bot, callback: dict, access: Access) -> None:
    """Вызывается только для человека из списка тревог в личке (проверяет диспетчер)."""
    key = (callback.get("data") or "")[2:]
    message = callback.get("message") or {}
    if not key or access.user_id is None:
        await bot.telegram.answer_callback(callback["id"], STALE_BUTTON)
        return
    until = bot.clock() + MUTE_SECONDS
    await bot.store.set_mute(key, until, access.user_id)
    clock = datetime.fromtimestamp(until, ZoneInfo(bot.config.timezone)).strftime("%H:%M")
    text = f"{esc(message.get('text') or '')}\n🔕 заглушено до {clock}"
    await bot.edit_and_answer(callback["id"], access.chat_id, message["message_id"], text, None,
                              MUTED_NOTE)


def install(bot: Bot) -> None:
    """Подключить кнопку «заглушить» к боту (подменяет крючок Bot.on_mute_callback)."""
    async def handler(callback: dict, access: Access) -> None:
        await on_mute(bot, callback, access)

    bot.on_mute_callback = handler  # type: ignore[method-assign]
