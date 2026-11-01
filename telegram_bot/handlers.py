"""Обработка обновлений Telegram: команды, кнопки, подключение чатов, рассылка.

В журнал попадают только виды обновлений и классы ошибок: ни текстов
сообщений, ни токена, ни Telegram ID.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from . import content, settings
from .access import Access, access_for, allowed
from .config import BotConfig
from .emoji import describe_custom_emoji, icon
from .render import (
    TELEGRAM_LIMIT,
    Message,
    decode_callback,
    encode_callback,
    esc,
    our_week_stats,
    period_label,
    render_help,
    render_top,
    render_week,
    split_message,
    text_only,
    week_label,
)
from .source import ApiSource, SourceUnavailable, person_request
from .servers import LIST_DATA, ServerMonitor, parse_data, server_buttons
from .status import STATUS_WINDOW_SECONDS, render_status
from .store import OUR_INSTITUTION, Recipient, Store
from .telegram import BotBlocked, CannotInitiate, TelegramClient, TelegramError
from .words import TopQuery, parse_top, split_command

log = logging.getLogger(__name__)

Flag = Literal["digest", "spike", "anomaly", "alerts"]
FLAGS = ("digest", "spike", "anomaly", "alerts")

NO_ACCESS = "Доступа нет. Пришлите админу бота свой ID — его покажет /id."
NO_OURS = "админ ещё не выбрал наш вуз: /settings"
SOURCE_DOWN = "данные временно недоступны, попробуйте позже"
STATUS_REFUSED = "Статус сервера — только в личке и только людям из списка тревог."
SETTINGS_REFUSED = "Настройки — только админу бота и только в личке."
UNKNOWN_COMMAND = "Не знаю такой команды. Список — в /help."
NOT_UNDERSTOOD = "Не понял. Команды — в /help."
ANSWER_BELOW = "ответ ниже"
MUTE_REFUSED = "заглушать тревоги можно только в личке, из списка тревог"
STALE_BUTTON = "кнопка устарела"
FOREIGN_MENU = "Это меню вызвал другой участник — напишите свой /top"
MAX_CHOICES = 8

BASE_COMMANDS = [
    ("top", "лучшие посты: /top все тг, /top мфти месяц"),
    ("week", "неделя к неделе и прогноз места в М-Рейтинге"),
    ("digest", "дайджест прямо сейчас"),
    ("help", "справка по командам"),
    ("id", "ваш Telegram ID"),
]
STATUS_COMMAND = ("status", "главные проверки сервера и сбора")
SETTINGS_COMMAND = ("settings", "наш вуз, чат, люди и подписки")
_MEMBER_STATUSES = frozenset({"member", "administrator", "creator"})
_GONE_STATUSES = frozenset({"left", "kicked"})


@dataclass(frozen=True)
class BroadcastResult:
    delivered: int  # скольким дошли все части
    transient: int  # скольким не дошло из-за временного сбоя Telegram


class _NoOurs(Exception):
    """Запрос про «наших», а наш вуз ещё не выбран."""


def person_commands(r: Recipient) -> list[tuple[str, str]]:
    """Меню совпадает с allowed(): /status — списку тревог, /settings — админу."""
    commands = list(BASE_COMMANDS)
    if r.alerts:
        commands.append(STATUS_COMMAND)
    if r.is_admin:
        commands.append(SETTINGS_COMMAND)
    return commands


def menu_author(message: dict) -> int | None:
    """Кто вызвал меню: id человека, а от имени чата (анонимный админ группы,
    пост канала) — id этого чата: «from» тогда — служебный бот Telegram."""
    sender = message.get("sender_chat")
    value = (sender or {}).get("id") if sender else (message.get("from") or {}).get("id")
    return value if isinstance(value, int) and not isinstance(value, bool) and value != 0 else None


def foreign_press(author: int | None, access: Access) -> bool:
    """Нажал не тот, кто вызвал меню. Замок — только в группах; кнопки без автора
    (отправленные до замка) слушаются всех. Автор-чат (отрицательный id): кто
    нажимает от имени чата, Telegram в callback не сообщает — в «from» всегда
    живой человек, и сверить его с чатом нельзя, поэтому такое меню слушается всех."""
    if access.private or author is None or author < 0:
        return False
    return access.user_id != author


def largest_file_id(result: dict | None) -> str | None:
    """file_id самого большого размера из ответа sendPhoto (порядок размеров
    Telegram не обещает)."""
    def number(value: object) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    sizes = [size for size in (result or {}).get("photo") or []
             if isinstance(size, dict) and isinstance(size.get("file_id"), str)]
    if not sizes:
        return None
    best = max(sizes, key=lambda size: (number(size.get("width")) * number(size.get("height")),
                                        number(size.get("file_size"))))
    return best["file_id"]


def _is_member(member: dict) -> bool:
    status = member.get("status")
    return status in _MEMBER_STATUSES or (status == "restricted" and bool(member.get("is_member")))


TYPING_REPEAT_SECONDS = 4.0  # Telegram гасит «печатает…» примерно через 5 с


class _Typing:
    """«печатает…» в чате, пока бот ждёт данные, которых нет в копии: шлётся
    сразу и повторяется, пока разбор обновления не закончится. Сбой — не повод
    отказать в ответе, поэтому ошибки только в журнал."""

    def __init__(self, telegram: TelegramClient, chat_id: int) -> None:
        self._telegram = telegram
        self._chat_id = chat_id
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                await self._telegram.send_typing(self._chat_id)
            except Exception as error:  # noqa: BLE001 - индикатор необязателен
                log.debug("typing: %s", type(error).__name__)
                return
            await asyncio.sleep(TYPING_REPEAT_SECONDS)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


def _update_chat(update: dict) -> int | None:
    message = update.get("message") or (update.get("callback_query") or {}).get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    return chat_id if isinstance(chat_id, int) else None


class Bot:
    def __init__(self, telegram: TelegramClient, source: ApiSource, store: Store,
                 config: BotConfig, clock: Callable[[], float] = time.time) -> None:
        self.telegram = telegram
        self.source = source
        self.store = store
        self.config = config
        self.clock = clock
        # Ожидание ввода в /settings: id админа → что ждём («our», «add»).
        self.pending: dict[int, str] = {}
        # Имя бота из getMe: в группах команды «/x@чужой_бот» пропускаем.
        self.username: str | None = None
        # Серверы под /status: кэш, кулдаун кнопок и живые сеансы.
        self.servers = ServerMonitor(store, clock, config.timezone)

    # --- запуск ---------------------------------------------------------

    async def setup(self) -> None:
        if not self.config.admin_ids:
            log.warning("администраторы не заданы: бот отвечает только на /start и /id")
        try:
            self.username = (await self.telegram.get_me()).get("username") or None
        except TelegramError as error:
            log.warning("get_me: %s", type(error).__name__)
        known = {r.chat_id: r for r in await self.store.recipients()}
        for admin_id in sorted(self.config.admin_ids):
            existing = known.get(admin_id)
            if existing is None:
                fresh = Recipient(admin_id, "person", str(admin_id), is_admin=True, alerts=True)
                await self.store.upsert_recipient(fresh, None)
            elif existing.kind == "person" and not existing.is_admin:
                await self.store.upsert_recipient(replace(existing, is_admin=True), None)
        await self._set_commands(BASE_COMMANDS, {"type": "default"})
        await self._set_commands(BASE_COMMANDS, {"type": "all_group_chats"})
        for r in await self.store.recipients():
            if r.kind == "person" and (r.is_admin or r.alerts):
                await self.sync_person_commands(r)

    async def _set_commands(self, commands: list[tuple[str, str]], scope: dict) -> None:
        try:
            await self.telegram.set_commands(commands, scope)
        except TelegramError as error:
            # Чата человека может ещё не быть (не писал боту) — меню подождёт.
            log.warning("set_commands %s: %s", scope.get("type"), type(error).__name__)

    async def sync_person_commands(self, r: Recipient | None, chat_id: int | None = None) -> None:
        """Меню «/» человека; для убранного (r=None) — общий набор."""
        target = r.chat_id if r is not None else chat_id
        if target is None:
            return
        commands = person_commands(r) if r is not None else list(BASE_COMMANDS)
        await self._set_commands(commands, {"type": "chat", "chat_id": target})

    # --- переопределяемые крючки (Task 12) ---------------------

    async def send_digest_here(self, chat_id: int) -> None:
        """/digest: тот же дайджест, что по понедельникам, но только в этот чат."""
        try:
            messages = await content.build_digest(self)
        except content.NoOurInstitution:
            await self.reply(chat_id, NO_OURS)
            return
        except SourceUnavailable as error:
            log.warning("digest: %s", type(error).__name__)
            await self.reply(chat_id, SOURCE_DOWN)
            return
        await self.send_all(chat_id, messages)

    async def on_mute_callback(self, callback: dict, access: Access) -> None:
        """Вызывается только для человека из списка тревог в личке."""
        await self.telegram.answer_callback(callback["id"], "недоступно")

    # --- рассылка -------------------------------------------------------

    async def broadcast(self, text_or_messages: str | Message | list[Message], flag: Flag) -> int:
        """Разослать всем с флагом; вернуть, скольким дошли все части.
        Тревоги — только людям, что бы ни лежало в хранилище."""
        return (await self.broadcast_report(text_or_messages, flag)).delivered

    async def broadcast_report(self, text_or_messages: str | Message | list[Message],
                               flag: Flag) -> BroadcastResult:
        """То же, что broadcast, но ещё и сколько получателей не получили из-за
        временного сбоя Telegram (их стоит попробовать ещё раз)."""
        if flag not in FLAGS:
            raise ValueError(f"неизвестный флаг рассылки: {flag!r}")
        if isinstance(text_or_messages, str):
            messages = [Message(part) for part in split_message(text_or_messages)]
        elif isinstance(text_or_messages, Message):
            messages = [text_or_messages]
        else:
            messages = list(text_or_messages)
        delivered = transient = 0
        uploaded: dict[bytes, str] = {}  # картинка грузится один раз, дальше — file_id
        for r in await self.store.recipients():
            if not getattr(r, flag) or (flag == "alerts" and r.kind != "person"):
                continue
            try:
                await self._send_parts(r.chat_id, messages, uploaded)
            except BotBlocked:
                log.info("broadcast %s: recipient %s unreachable, removed", flag, r.kind)
                await self.store.remove_recipient(r.chat_id)
                continue
            except CannotInitiate as error:
                # Человек ещё не нажал /start: оставляем, дойдёт после.
                log.info("broadcast %s: %s", flag, type(error).__name__)
                continue
            except TelegramError as error:
                log.warning("broadcast %s: %s", flag, type(error).__name__)
                transient += 1
                continue
            delivered += 1
        return BroadcastResult(delivered, transient)

    # --- отправка -------------------------------------------------------

    async def reply(self, chat_id: int, text: str, keyboard: list[list[dict]] | None = None) -> dict:
        return await self.telegram.send_message(chat_id, text, keyboard)

    async def send_all(self, chat_id: int, messages: list[Message]) -> None:
        await self._send_parts(chat_id, messages, {})

    async def _send_parts(self, chat_id: int, messages: list[Message],
                          uploaded: dict[bytes, str]) -> None:
        """Все части одному чату. Картинка: если её уже загружали (`uploaded`:
        байты → file_id), уходит по file_id. Telegram её не принял (TelegramError,
        не BotBlocked/CannotInitiate) — этому чату только текст, подпись встаёт
        в начало следующей части; картинку не повторяем. Отказ по file_id
        забывает его: следующий получатель загрузит байты заново."""
        parts = list(messages)
        index = 0
        while index < len(parts):
            message = parts[index]
            if message.photo is None:
                await self.telegram.send_message(chat_id, message.text, message.keyboard)
                index += 1
                continue
            try:
                result = await self.telegram.send_photo(
                    chat_id, uploaded.get(message.photo, message.photo), message.text)
            except (BotBlocked, CannotInitiate):
                raise
            except TelegramError as error:
                log.warning("send_photo: %s", type(error).__name__)
                uploaded.pop(message.photo, None)
                parts[index:] = text_only(parts[index:])
                continue
            file_id = largest_file_id(result)
            if file_id is not None:
                uploaded.setdefault(message.photo, file_id)
            index += 1

    async def edit_and_answer(self, callback_id: str, chat_id: int, message_id: int, text: str,
                              keyboard: list[list[dict]] | None, note: str | None = None) -> None:
        """Правка сообщения под кнопкой; ответ на нажатие уходит и при сбое правки,
        иначе у человека крутится часик."""
        try:
            await self.telegram.edit_message(chat_id, message_id, text, keyboard)
        finally:
            await self.telegram.answer_callback(callback_id, note)

    # --- разбор обновлений ----------------------------------------------

    async def handle(self, update: dict) -> None:
        kind = next((key for key in update if key != "update_id"), "empty")
        log.debug("update %s", kind)
        chat_id = _update_chat(update)
        typing = _Typing(self.telegram, chat_id) if chat_id is not None else None
        try:
            # Человеку — из копии до часа; холодные данные — с «печатает…».
            with person_request(typing.start if typing is not None else None):
                if "message" in update:
                    await self._on_message(update["message"])
                elif "callback_query" in update:
                    await self._on_callback(update["callback_query"])
                elif "my_chat_member" in update:
                    await self._on_membership(update["my_chat_member"])
        except TelegramError as error:
            log.warning("update %s: %s", kind, type(error).__name__)
        finally:
            if typing is not None:
                await typing.stop()

    async def _on_message(self, message: dict) -> None:
        chat = message.get("chat") or {}
        if "id" not in chat:
            return
        if "migrate_to_chat_id" in message:
            await self.store.migrate_chat(chat["id"], message["migrate_to_chat_id"])
            return
        if "migrate_from_chat_id" in message:
            await self.store.migrate_chat(message["migrate_from_chat_id"], chat["id"])
            return
        private = chat.get("type") == "private"
        text = message.get("text") or ""
        command, args = split_command(text)
        if not private and (command is None or not text.lstrip().startswith("/")
                            or self._addressed_elsewhere(text)):
            # В группе — только слэш-команды нам; обычная переписка не стоит чтения базы.
            return
        access = access_for(message, await self.store.recipients())
        if not private and not access.known_chat:
            # Чат не подключён. Выходим лениво, по первой команде: при переходе группы в
            # супергруппу my_chat_member нового id может прийти раньше migrate_from_chat_id.
            await self._leave(chat["id"])
            return
        waiting = access.user_id in self.pending if access.user_id is not None else False
        if waiting and access.private and access.admin and (command is None or "forward_origin" in message):
            await settings.on_input(self, access, message)
            return
        if access.user_id is not None:
            self.pending.pop(access.user_id, None)  # любая команда отменяет ожидание ввода
        if "sticker" in message and access.private and access.admin:
            # Админ прислал стикер — показать его id для таблицы слотов значков.
            await self.reply(chat["id"], describe_custom_emoji(message))
            return
        if command == "emoji" and allowed("emoji", access):
            await self.reply(chat["id"], describe_custom_emoji(message))
            return
        if command is None:
            if access.private:
                await self.reply(chat["id"], NOT_UNDERSTOOD if access.known_person else NO_ACCESS)
            return
        # Автор меню нужен только в группах: в личке нажимать больше некому.
        await self._on_command(command, args, access, None if private else menu_author(message))

    async def _on_command(self, command: str, args: str, access: Access,
                          author: int | None = None) -> None:
        chat_id = access.chat_id
        if not allowed(command, access):
            if not access.known:
                await self.reply(chat_id, NO_ACCESS)
            elif command == "status":
                await self.reply(chat_id, STATUS_REFUSED)
            elif command == "settings":
                await self.reply(chat_id, SETTINGS_REFUSED)
            elif access.private:
                await self.reply(chat_id, UNKNOWN_COMMAND)
            # В группе чужие команды (другим ботам) молча пропускаем.
            return
        if command == "id":
            await self.reply(chat_id, self._id_text(access))
        elif command == "start":
            if access.known:
                await self.reply(chat_id, self._help(access))
            else:
                await self.reply(chat_id, f"{icon('logo')} <b>m-ranked</b> · бот мониторинга вузов\n\n"
                                          f"{self._id_text(access)}\n"
                                          "Пришлите его админу бота, чтобы получить доступ.")
        elif command == "help":
            await self.reply(chat_id, self._help(access))
        elif command == "top":
            await self._top_command(chat_id, args, author)
        elif command == "week":
            await self._week(chat_id)
        elif command == "digest":
            await self.send_digest_here(chat_id)
        elif command == "status":
            message = await self._status_message()
            await self.reply(chat_id, message.text, message.keyboard)
        elif command == "settings":
            await settings.open_menu(self, access)

    async def _status_message(self) -> Message:
        rows = await self.store.status_rows(STATUS_WINDOW_SECONDS)
        servers = await self.servers.servers()
        return render_status(rows, self.clock(), self.config.timezone, servers=server_buttons(servers))

    async def _status_callback(self, callback: dict, access: Access, message: dict) -> None:
        """Кнопки под /status и под сервером: те же условия, что у самой команды
        (получатель тревог, личка); нажатия чата — не чаще раза в 3 с."""
        if not (access.alerts and access.private):
            await self.telegram.answer_callback(callback["id"], "недоступно")
            return
        chat_id, message_id = access.chat_id, message["message_id"]
        data = callback.get("data") or ""
        if self.servers.pressed_too_often(chat_id):
            await self.telegram.answer_callback(callback["id"], "не так часто — раз в 3 секунды")
            return
        if data == LIST_DATA:
            self.servers.stop_live(chat_id)
            fresh = await self._status_message()
            # Текст не изменился — Telegram ответит «not modified», клиент это глотает.
            await self.edit_and_answer(callback["id"], chat_id, message_id, fresh.text, fresh.keyboard, "обновлено")
            return
        parsed = parse_data(data)
        item = None
        if parsed is not None:
            item = next((entry for entry in await self.servers.servers() if entry["id"] == parsed[1]), None)
        if parsed is None or item is None:
            await self.telegram.answer_callback(callback["id"], STALE_BUTTON)
            return
        action, server = parsed
        note = None
        live_until = None
        if action == "v":
            kind = "main" if item["role"] == "main" else "node"

            async def edit(fresh: Message) -> None:
                await self.telegram.edit_message(chat_id, message_id, fresh.text, fresh.keyboard)

            if self.servers.start_live(chat_id, message_id, server, kind, edit):
                live_until = self.servers.live[chat_id].until
                note = "вживую 2 минуты"
            else:
                note = "сейчас смотрят другие — попробуйте через пару минут"
        elif action == "x":
            self.servers.stop_live(chat_id)
            note = "остановлено"
        else:
            # Другой сервер или «Обновить» — прежний живой сеанс этого чата не нужен.
            live = self.servers.live.get(chat_id)
            if live is not None and live.server != server:
                self.servers.stop_live(chat_id)
            elif live is not None:
                live_until = live.until
        fresh = await self.servers.message(server, live_until)
        if fresh is None:
            await self.telegram.answer_callback(callback["id"], STALE_BUTTON)
            return
        await self.edit_and_answer(callback["id"], chat_id, message_id, fresh.text, fresh.keyboard, note)

    def _addressed_elsewhere(self, text: str) -> bool:
        head = text.strip().split(None, 1)[0]
        if "@" not in head or self.username is None:
            return False
        return head.split("@", 1)[1].lower() != self.username.lower()

    async def _leave(self, chat_id: int) -> None:
        log.info("leaving a chat that is not connected")
        try:
            await self.telegram.leave_chat(chat_id)
        except TelegramError as error:
            log.warning("leave_chat: %s", type(error).__name__)

    @staticmethod
    def _id_text(access: Access) -> str:
        if access.user_id is None:
            return "Ваш ID не виден: сообщение отправлено от имени чата."
        return f"Ваш Telegram ID: <code>{access.user_id}</code>."

    @staticmethod
    def _help(access: Access) -> str:
        return render_help(alerts=access.private and access.alerts,
                           admin=access.private and access.admin)

    # --- /top -----------------------------------------------------------

    async def _top_messages(self, query: TopQuery, author: int | None = None) -> list[Message]:
        """Ответ на запрос; SourceUnavailable и _NoOurs — вызывающему."""
        our = await self.store.get_setting(OUR_INSTITUTION)
        if query.who == "ours" and our is None:
            raise _NoOurs
        body = await self.source.top_body(query, our)
        try:
            as_of = datetime.fromisoformat(body["asOf"])
        except (KeyError, TypeError, ValueError):
            as_of = datetime.fromtimestamp(self.clock(), ZoneInfo(self.config.timezone))
        return render_top(query, body, our, period_label(query.period, as_of), author)

    async def _top_command(self, chat_id: int, args: str, author: int | None = None) -> None:
        try:
            institutions = await self.source.institutions()
            query = parse_top(args, institutions)
            options = sorted(set(query.candidates) | ({query.institution} if query.candidates
                                                     and query.institution is not None else set()))
            if options:
                names = {inst.legacy_id: inst.short_name or inst.name for inst in institutions}
                base = replace(query, who="institution", unknown=(), candidates=(), suggestions=())
                keyboard = [[{"text": names.get(legacy_id, f"вуз №{legacy_id}"),
                              "callback_data": encode_callback(replace(base, institution=legacy_id),
                                                               author)}]
                            for legacy_id in options[:MAX_CHOICES]]
                await self.reply(chat_id, "Какой из них?", keyboard)
                return
            messages = await self._top_messages(query, author)
        except SourceUnavailable as error:
            log.warning("top: %s", type(error).__name__)
            await self.reply(chat_id, SOURCE_DOWN)
            return
        except _NoOurs:
            await self.reply(chat_id, NO_OURS)
            return
        if query.suggestions:
            hint = f"Может быть: {esc(', '.join(query.suggestions))}?"
            first = messages[0]
            if len(first.text) + 1 + len(hint) <= TELEGRAM_LIMIT:
                messages[0] = replace(first, text=f"{first.text}\n{hint}" if first.keyboard
                                      else f"{hint}\n{first.text}")
            else:
                messages.insert(0, Message(hint))
        await self.send_all(chat_id, messages)

    async def _top_callback(self, callback: dict, access: Access, message: dict) -> None:
        callback_id = callback["id"]
        decoded = decode_callback(callback.get("data") or "")
        if decoded is None:
            await self.telegram.answer_callback(callback_id, STALE_BUTTON)
            return
        query, author = decoded
        if not allowed("top", access):
            await self.telegram.answer_callback(callback_id, NO_ACCESS)
            return
        if foreign_press(author, access):
            # Сообщение не трогаем и API не читаем: только подсказка нажавшему.
            await self.telegram.answer_callback(callback_id, FOREIGN_MENU)
            return
        try:
            messages = await self._top_messages(query, author)
        except SourceUnavailable as error:
            log.warning("top callback: %s", type(error).__name__)
            await self.telegram.answer_callback(callback_id, SOURCE_DOWN)
            return
        except _NoOurs:
            await self.telegram.answer_callback(callback_id, NO_OURS)
            return
        if len(messages) == 1:
            await self.edit_and_answer(callback_id, access.chat_id, message["message_id"],
                                       messages[0].text, messages[0].keyboard)
            return
        # Несколько частей в одно сообщение не влезут: шлём заново, старое остаётся.
        await self.send_all(access.chat_id, messages)
        await self.telegram.answer_callback(callback_id, ANSWER_BELOW)

    # --- /week ----------------------------------------------------------

    async def _week(self, chat_id: int) -> None:
        our = await self.store.get_setting(OUR_INSTITUTION)
        if our is None:
            await self.reply(chat_id, NO_OURS)
            return
        try:
            dashboard = await self.source.dashboard()
            forecast = await self.source.forecast()
        except SourceUnavailable as error:
            log.warning("week: %s", type(error).__name__)
            await self.reply(chat_id, SOURCE_DOWN)
            return
        today = datetime.fromtimestamp(self.clock(), ZoneInfo(self.config.timezone)).date()
        previous = await self.store.week_snapshot(today - timedelta(days=7))
        current, label = our_week_stats(dashboard, our), week_label(dashboard)
        data = await content.prepare_cover(dashboard, our, current, previous, label)
        messages = render_week(current, previous, forecast, our, cover=data, label=label)
        await self.send_all(chat_id, await content.with_cover(messages, data))

    # --- кнопки ---------------------------------------------------------

    async def _on_callback(self, callback: dict) -> None:
        data = callback.get("data") or ""
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        if "id" not in chat or "message_id" not in message:
            await self.telegram.answer_callback(callback["id"], STALE_BUTTON)
            return
        access = access_for({"chat": chat, "from": callback.get("from")}, await self.store.recipients())
        if data.startswith("t|"):
            await self._top_callback(callback, access, message)
        elif data.startswith("s|"):
            await settings.on_callback(self, callback, access, message)
        elif data.startswith("st|"):
            await self._status_callback(callback, access, message)
        elif data.startswith("m|"):
            if access.alerts and access.private:
                await self.on_mute_callback(callback, access)
            else:
                await self.telegram.answer_callback(callback["id"], MUTE_REFUSED)
        else:
            await self.telegram.answer_callback(callback["id"], STALE_BUTTON)

    # --- членство бота в чатах ------------------------------------------

    async def is_admin(self, user_id: int | None) -> bool:
        if user_id is None:
            return False
        if user_id in self.config.admin_ids:
            return True
        return any(r.chat_id == user_id and r.kind == "person" and r.is_admin
                   for r in await self.store.recipients())

    async def _on_membership(self, update: dict) -> None:
        chat = update.get("chat") or {}
        if "id" not in chat or chat.get("type") == "private":
            # Блокировку в личке разберёт рассылка (BotBlocked).
            return
        chat_id = chat["id"]
        new = update.get("new_chat_member") or {}
        if new.get("status") in _GONE_STATUSES:
            await self.store.remove_recipient(chat_id)
            log.info("membership: bot removed from a chat")
            return
        if not _is_member(new):
            return
        title = chat.get("title") or str(chat_id)
        known = next((r for r in await self.store.recipients() if r.chat_id == chat_id), None)
        if known is not None:
            # Повышение или смена прав в уже подключённом чате: флаги не трогаем.
            if known.kind == "chat" and known.title != title:
                await self.store.upsert_recipient(replace(known, title=title), None)
            return
        by = (update.get("from") or {}).get("id")
        if await self.is_admin(by):
            await self.store.upsert_recipient(
                Recipient(chat_id, "chat", title, digest=True, spike=True, anomaly=True), by)
            log.info("membership: chat connected by admin")
            return
        # Добавил не админ. Сразу не уходим: это может быть новый id той же группы после
        # перехода в супергруппу (migrate_from_chat_id придёт следом). Неподключённый чат
        # бот покинет по первой команде из него, а рассылки туда и так не идут.
        log.info("membership: added by non-admin, chat stays unconnected")
