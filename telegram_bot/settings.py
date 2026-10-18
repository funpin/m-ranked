"""/settings: наш вуз, рабочий чат, люди и подписки. Только админ, только в личке.

Кнопки — callback «s|…»; нажатие правит то же сообщение. Ввод текста (название
вуза, ID человека) ждётся в Bot.pending по id админа, в памяти.

  s|menu                 главное меню
  s|our                  ждать название нашего вуза
  s|our|<legacy id>      выбрать вуз из неоднозначных
  s|chats                подключённые чаты и их подписки
  s|ct|<chat id>|<d|s|a> переключить подписку чата (тревог у чата нет совсем)
  s|people               люди
  s|add                  ждать ID или пересланное сообщение
  s|p|<id>               карточка человека
  s|pt|<id>|<t|d|s|a|x>  переключить тревоги/дайджест/выстрелил/накрутку/админа
  s|pr|<id>              убрать человека
  s|me                   мои уведомления
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from .access import Access, allowed
from .emoji import icon
from .render import esc
from .source import SourceUnavailable
from .store import OUR_INSTITUTION, Recipient
from .words import Institution, parse_top

if TYPE_CHECKING:
    from .handlers import Bot

log = logging.getLogger(__name__)

WAIT_OUR = "our"
WAIT_PERSON = "add"
MAX_CHOICES = 8
MAX_USER_ID = 2**53
SOURCE_DOWN = "данные временно недоступны, попробуйте позже"
REFUSED = "Настройки — только админу бота и только в личке."
# Первым бот писать не может: пока человек не нажал /start, рассылки до него не дойдут.
START_HINT = "<i>Человек должен открыть бота и нажать /start — иначе сообщения до него не дойдут.</i>"

# Код в callback → поле Recipient и подпись кнопки.
PERSON_FLAGS = {"t": ("alerts", "Тревоги"), "d": ("digest", "Дайджест"),
                "s": ("spike", "Выстрелил"), "a": ("anomaly", "Накрутка"), "x": ("is_admin", "Админ")}
CHAT_FLAGS = {"d": ("digest", "Дайджест"), "s": ("spike", "Выстрелил"), "a": ("anomaly", "Накрутка")}

Screen = tuple[str, list[list[dict]]]


def _button(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


def _toggle(label: str, on: bool, data: str) -> dict:
    return _button(f"{'✅' if on else '⬜'} {label}", data)


BACK_TO_MENU = [_button("« Настройки", "s|menu")]


def _institution_name(institutions: list[Institution], legacy_id: int) -> str:
    inst = next((i for i in institutions if i.legacy_id == legacy_id), None)
    if inst is None:
        return f"вуз №{legacy_id}"
    return f"{inst.short_name} ({inst.name})" if inst.short_name else inst.name


# --- экраны -------------------------------------------------------------

async def _menu(bot: Bot) -> Screen:
    our = await bot.store.get_setting(OUR_INSTITUTION)
    if our is None:
        our_text = "не выбран"
    else:
        try:
            our_text = _institution_name(await bot.source.institutions(), our)
        except SourceUnavailable:
            our_text = f"вуз №{our}"
    recipients = await bot.store.recipients()
    chats = sum(1 for r in recipients if r.kind == "chat")
    people = sum(1 for r in recipients if r.kind == "person")
    text = "\n".join([f"{icon('logo')} <b>Настройки</b>", "",
                      f"Наш вуз: <b>{esc(our_text)}</b>",
                      f"Рабочих чатов: <b>{chats}</b> · людей: <b>{people}</b>"])
    keyboard = [[_button("🏛 Наш вуз", "s|our"), _button("💬 Рабочий чат", "s|chats")],
                [_button("👤 Люди", "s|people"), _button("🔔 Мои уведомления", "s|me")]]
    return text, keyboard


async def _chats(bot: Bot) -> Screen:
    chats = [r for r in await bot.store.recipients() if r.kind == "chat"]
    lines = ["<b>Рабочий чат</b>"]
    keyboard: list[list[dict]] = []
    if not chats:
        lines.append("Чат не подключён: добавьте бота в группу от своего имени.")
    for number, chat in enumerate(chats, 1):
        prefix = f"{number}: " if len(chats) > 1 else ""
        lines.append(f"{number}. {esc(chat.title)}" if len(chats) > 1 else esc(chat.title))
        keyboard.append([_toggle(prefix + label, getattr(chat, field), f"s|ct|{chat.chat_id}|{code}")
                         for code, (field, label) in CHAT_FLAGS.items()])
    lines.append("<i>Тревоги приходят только людям в личку.</i>")
    keyboard.append(BACK_TO_MENU)
    return "\n".join(lines), keyboard


async def _people(bot: Bot) -> Screen:
    people = [r for r in await bot.store.recipients() if r.kind == "person"]
    lines = ["<b>Люди</b>"]
    for r in people:
        marks = [name for field, name in (("is_admin", "админ"), ("alerts", "тревоги"),
                                          ("digest", "дайджест"), ("spike", "выстрелил"),
                                          ("anomaly", "накрутка")) if getattr(r, field)]
        lines.append(f"• {esc(r.title)} — {', '.join(marks) or 'ничего не получает'}")
    keyboard = [[_button(f"👤 {r.title}", f"s|p|{r.chat_id}")] for r in people]
    keyboard.append([_button("➕ Добавить", "s|add")])
    keyboard.append(BACK_TO_MENU)
    return "\n".join(lines), keyboard


def _card(bot: Bot, r: Recipient, viewer: int | None) -> Screen:
    own = r.chat_id == viewer
    title = "Мои уведомления" if own else esc(r.title)
    lines = [f"<b>{title}</b>", f"Telegram ID: <code>{r.chat_id}</code>"]
    if r.is_admin:
        lines.append("Админ бота.")
    if not own:
        lines.append(START_HINT)
    flags = [(code, field, label) for code, (field, label) in PERSON_FLAGS.items() if code != "x"]
    keyboard = [[_toggle(label, getattr(r, field), f"s|pt|{r.chat_id}|{code}")
                 for code, field, label in flags[:2]],
                [_toggle(label, getattr(r, field), f"s|pt|{r.chat_id}|{code}")
                 for code, field, label in flags[2:]]]
    # Себя не убрать и прав не лишить; админов с сервера — тоже (вернутся при запуске).
    if not own and r.chat_id not in bot.config.admin_ids:
        keyboard.append([_toggle("Админ", r.is_admin, f"s|pt|{r.chat_id}|x"),
                         _button("🗑 Убрать", f"s|pr|{r.chat_id}")])
    keyboard.append(BACK_TO_MENU if own else [_button("« Люди", "s|people")])
    return "\n".join(lines), keyboard


async def _person(bot: Bot, chat_id: int) -> Recipient | None:
    return next((r for r in await bot.store.recipients()
                 if r.chat_id == chat_id and r.kind == "person"), None)


def _choices(institutions: list[Institution], options: list[int]) -> Screen:
    names = {i.legacy_id: i.short_name or i.name for i in institutions}
    return "Какой из них?", [[_button(names.get(legacy_id, f"вуз №{legacy_id}"), f"s|our|{legacy_id}")]
                             for legacy_id in options[:MAX_CHOICES]] + [BACK_TO_MENU]


# --- вход из команды и из кнопок -----------------------------------------

async def open_menu(bot: Bot, access: Access) -> None:
    text, keyboard = await _menu(bot)
    await bot.reply(access.chat_id, text, keyboard)


def _int(part: str) -> int | None:
    try:
        return int(part)
    except ValueError:
        return None


async def on_callback(bot: Bot, callback: dict, access: Access, message: dict) -> None:
    callback_id = callback["id"]
    if not allowed("settings", access):
        await bot.telegram.answer_callback(callback_id, REFUSED)
        return
    admin = access.user_id
    parts = (callback.get("data") or "").split("|")[1:]
    action, args = (parts[0] if parts else ""), parts[1:]
    note: str | None = None
    screen: Screen | None = None
    if action != "add" and action != "our":
        bot.pending.pop(admin, None)
    if action == "menu":
        screen = await _menu(bot)
    elif action == "our" and not args:
        bot.pending[admin] = WAIT_OUR
        screen = ("Напишите название нашего вуза — коротко или полностью.", [BACK_TO_MENU])
    elif action == "our" and len(args) == 1 and _int(args[0]) is not None:
        bot.pending.pop(admin, None)
        try:
            institutions = await bot.source.institutions()
        except SourceUnavailable:
            await bot.telegram.answer_callback(callback_id, SOURCE_DOWN)
            return
        screen = await _save_ours(bot, admin, institutions, _int(args[0]))
    elif action == "chats":
        screen = await _chats(bot)
    elif action == "ct" and len(args) == 2 and _int(args[0]) is not None and args[1] in CHAT_FLAGS:
        chat = next((r for r in await bot.store.recipients()
                     if r.chat_id == _int(args[0]) and r.kind == "chat"), None)
        if chat is None:
            note = "чат уже не подключён"
        else:
            field = CHAT_FLAGS[args[1]][0]
            await bot.store.upsert_recipient(replace(chat, **{field: not getattr(chat, field)}), admin)
        screen = await _chats(bot)
    elif action == "people":
        screen = await _people(bot)
    elif action == "add" and not args:
        bot.pending[admin] = WAIT_PERSON
        screen = ("Пришлите числовой Telegram ID человека (его покажет /id) "
                  "или перешлите сюда его сообщение.", [[_button("« Люди", "s|people")]])
    elif action in ("p", "pt", "pr", "me"):
        screen, note = await _person_action(bot, action, args, admin)
    if screen is None:
        await bot.telegram.answer_callback(callback_id, "кнопка устарела")
        return
    await bot.edit_and_answer(callback_id, access.chat_id, message["message_id"],
                              screen[0], screen[1], note)


async def _person_action(bot: Bot, action: str, args: list[str], admin: int) -> tuple[Screen | None, str | None]:
    target = admin if action == "me" else (_int(args[0]) if args else None)
    if target is None:
        return None, None
    r = await _person(bot, target)
    if r is None:
        return await _people(bot), "такого человека нет в списке"
    if action in ("p", "me"):
        return _card(bot, r, admin), None
    protected = r.chat_id == admin or r.chat_id in bot.config.admin_ids
    if action == "pr":
        if protected:
            return _card(bot, r, admin), "этого человека убрать нельзя"
        await bot.store.remove_recipient(r.chat_id)
        await bot.sync_person_commands(None, r.chat_id)
        return await _people(bot), "убран"
    code = args[1] if len(args) == 2 else ""
    if code not in PERSON_FLAGS or (code == "x" and protected):
        return _card(bot, r, admin), "нельзя"
    field = PERSON_FLAGS[code][0]
    updated = replace(r, **{field: not getattr(r, field)})
    await bot.store.upsert_recipient(updated, admin)
    if field in ("alerts", "is_admin"):
        await bot.sync_person_commands(updated)
    return _card(bot, updated, admin), None


async def _save_ours(bot: Bot, admin: int, institutions: list[Institution], legacy_id: int) -> Screen:
    if not any(i.legacy_id == legacy_id for i in institutions):
        return "Такого вуза нет в каталоге.", [BACK_TO_MENU]
    await bot.store.set_setting(OUR_INSTITUTION, legacy_id, admin)
    log.info("settings: our institution changed")
    return f"Наш вуз: <b>{esc(_institution_name(institutions, legacy_id))}</b>", [BACK_TO_MENU]


# --- ввод текста ---------------------------------------------------------

async def on_input(bot: Bot, access: Access, message: dict) -> None:
    admin = access.user_id
    waiting = bot.pending.get(admin)
    if waiting == WAIT_OUR:
        await _input_ours(bot, access, (message.get("text") or "").strip())
    elif waiting == WAIT_PERSON:
        await _input_person(bot, access, message)
    else:
        bot.pending.pop(admin, None)


async def _input_ours(bot: Bot, access: Access, text: str) -> None:
    if not text:
        await bot.reply(access.chat_id, "Нужно название вуза текстом.")
        return
    try:
        institutions = await bot.source.institutions()
    except SourceUnavailable:
        await bot.reply(access.chat_id, SOURCE_DOWN)
        return
    query = parse_top(text, institutions)
    options = sorted(set(query.candidates) | ({query.institution} if query.institution is not None else set()))
    if not options:
        hint = f" Похожие: {esc(', '.join(query.suggestions))}." if query.suggestions else ""
        await bot.reply(access.chat_id, f"Не нашёл «{esc(text)}».{hint} Напишите иначе.")
        return
    bot.pending.pop(access.user_id, None)
    if len(options) == 1:
        screen = await _save_ours(bot, access.user_id, institutions, options[0])
    else:
        screen = _choices(institutions, options)
    await bot.reply(access.chat_id, *screen)


def _person_from(message: dict) -> tuple[int | None, str | None, str | None]:
    """(id, имя, ошибка) из пересланного сообщения или из текста с числом."""
    origin = message.get("forward_origin")
    if isinstance(origin, dict):
        if origin.get("type") != "user" or not isinstance(origin.get("sender_user"), dict):
            return None, None, ("Telegram скрыл, чьё это сообщение. Попросите человека прислать /id "
                                "и пришлите мне число.")
        user = origin["sender_user"]
    elif isinstance(message.get("forward_from"), dict):
        user = message["forward_from"]
    else:
        text = (message.get("text") or "").strip()
        value = int(text) if text.isascii() and text.isdigit() else None
        if value is None or not 0 < value < MAX_USER_ID:
            return None, None, "Нужен числовой Telegram ID (его покажет /id) или пересланное сообщение."
        return value, None, None
    if user.get("is_bot"):
        return None, None, "Это бот, а не человек."
    name = " ".join(part for part in (user.get("first_name"), user.get("last_name")) if part)
    return user.get("id"), name or user.get("username"), None


async def _input_person(bot: Bot, access: Access, message: dict) -> None:
    user_id, name, error = _person_from(message)
    if error is not None or not isinstance(user_id, int):
        await bot.reply(access.chat_id, error or "Не удалось понять, кто это.")
        return
    bot.pending.pop(access.user_id, None)
    existing = await _person(bot, user_id)
    if existing is None:
        existing = Recipient(user_id, "person", name or str(user_id))
        await bot.store.upsert_recipient(existing, access.user_id)
        log.info("settings: person added")
    await bot.reply(access.chat_id, *_card(bot, existing, access.user_id))
