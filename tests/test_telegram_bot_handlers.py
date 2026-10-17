"""Команды, кнопки, доступ и подключение чата: Bot на подделках Telegram и API."""
from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from telegram_bot.access import Access, access_for, allowed
from telegram_bot.config import BotConfig
from telegram_bot.handlers import Bot
from telegram_bot.render import Message, decode_callback, encode_callback
from telegram_bot.source import SourceUnavailable
from telegram_bot.status import render_status
from telegram_bot.store import OUR_INSTITUTION, MemoryStore, Recipient
from telegram_bot.telegram import BotBlocked, TelegramError
from telegram_bot.words import Institution, TopQuery

FIXTURES = Path(__file__).parent / "fixtures" / "telegram_bot"
OUR_ID = 4
ADMIN = 7
PERSON = 21
STRANGER = 99
GROUP = -500
NOW = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc).timestamp()


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeTelegram:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.blocked: set[int] = set()
        self.failing: set[int] = set()
        self._next_id = 100

    def of(self, name: str) -> list[tuple]:
        return [call for call in self.calls if call[0] == name]

    async def send_message(self, chat_id, text, keyboard=None):
        if chat_id in self.blocked:
            raise BotBlocked(chat_id)
        if chat_id in self.failing:
            raise TelegramError("sendMessage: Telegram ответил 500")
        self._next_id += 1
        self.calls.append(("send", chat_id, text, keyboard, self._next_id))
        return {"message_id": self._next_id, "chat": {"id": chat_id}}

    async def edit_message(self, chat_id, message_id, text, keyboard=None):
        self.calls.append(("edit", chat_id, message_id, text, keyboard))

    async def answer_callback(self, callback_id, text=None):
        self.calls.append(("answer", callback_id, text))

    async def set_commands(self, commands, scope):
        self.calls.append(("commands", [name for name, _ in commands], scope))

    async def leave_chat(self, chat_id):
        self.calls.append(("leave", chat_id))


class FakeSource:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.down = False
        self.body: dict | None = None

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.down:
            raise SourceUnavailable(f"{name}: ConnectError")

    async def institutions(self) -> list[Institution]:
        self._call("institutions")
        return [Institution(e["legacyId"], e.get("shortName"), e["canonicalName"])
                for e in fixture("findings_all.json")["institutions"]]

    async def top_body(self, query: TopQuery, our_id: int | None) -> dict:
        self._call("top_body")
        if self.body is not None:
            return copy.deepcopy(self.body)
        return fixture("findings_all.json" if query.who == "all" else "findings_institution.json")

    async def dashboard(self) -> dict:
        self._call("dashboard")
        return fixture("dashboard.json")

    async def forecast(self) -> dict | None:
        self._call("forecast")
        return fixture("forecast.json")


def make_bot(*, our: int | None = OUR_ID, recipients: list[Recipient] | None = None):
    telegram, source, store = FakeTelegram(), FakeSource(), MemoryStore()
    config = BotConfig(token="test-token", admin_ids=frozenset({ADMIN}), api_base_url="http://api.test",
                       dsn="postgresql://test", spool_dir=Path("/nonexistent"))
    bot = Bot(telegram, source, store, config, clock=lambda: NOW)

    async def seed() -> None:
        if our is not None:
            await store.set_setting(OUR_INSTITUTION, our, ADMIN)
        for recipient in recipients if recipients is not None else [
            Recipient(ADMIN, "person", "админ", is_admin=True, alerts=True),
            Recipient(PERSON, "person", "человек", digest=True),
            Recipient(GROUP, "chat", "рабочий чат", digest=True, spike=True, anomaly=True),
        ]:
            await store.upsert_recipient(recipient, None)

    asyncio.run(seed())
    return bot, telegram, source, store


def private_message(user: int, text: str, **extra) -> dict:
    return {"update_id": 1, "message": {"message_id": 5, "chat": {"id": user, "type": "private"},
                                         "from": {"id": user, "first_name": "Имя"}, "text": text, **extra}}


def group_message(user: int, text: str, chat: int = GROUP) -> dict:
    return {"update_id": 1, "message": {"message_id": 5, "chat": {"id": chat, "type": "supergroup",
                                                                  "title": "Группа"},
                                         "from": {"id": user, "first_name": "Имя"}, "text": text}}


def callback(user: int, chat: int, message_id: int, data: str, chat_type: str = "private") -> dict:
    return {"update_id": 2, "callback_query": {
        "id": "cb1", "from": {"id": user}, "data": data,
        "message": {"message_id": message_id, "chat": {"id": chat, "type": chat_type}}}}


def handle(bot: Bot, update: dict) -> None:
    asyncio.run(bot.handle(update))


def sent_texts(telegram: FakeTelegram, chat_id: int | None = None) -> list[str]:
    return [call[2] for call in telegram.of("send") if chat_id is None or call[1] == chat_id]


def buttons(keyboard: list[list[dict]] | None) -> list[dict]:
    return [button for row in keyboard or [] for button in row]


def button_by_text(keyboard, fragment: str) -> dict:
    found = [b for b in buttons(keyboard) if fragment in b["text"]]
    assert found, f"нет кнопки «{fragment}» среди {[b['text'] for b in buttons(keyboard)]}"
    return found[0]


# --- доступ ----------------------------------------------------------------

def _access(**kwargs) -> Access:
    base = dict(user_id=1, chat_id=1, private=True, admin=False, alerts=False,
                known_person=False, known_chat=False)
    return Access(**{**base, **kwargs})


def test_allowed_matrix():
    stranger = _access()
    person = _access(known_person=True)
    alerts_person = _access(known_person=True, alerts=True)
    admin = _access(known_person=True, admin=True, alerts=True)
    group = _access(private=False, chat_id=GROUP, known_chat=True)
    alerts_in_group = _access(private=False, chat_id=GROUP, known_chat=True, known_person=True, alerts=True,
                              admin=True)
    for command in ("top", "week", "digest", "help"):
        assert not allowed(command, stranger)
        assert allowed(command, person) and allowed(command, group) and allowed(command, admin)
    for command in ("id", "start"):
        for access in (stranger, person, group, admin):
            assert allowed(command, access)
    assert allowed("status", alerts_person) and allowed("status", admin)
    assert not allowed("status", person) and not allowed("status", group)
    assert not allowed("status", alerts_in_group)
    assert allowed("settings", admin)
    assert not allowed("settings", alerts_person) and not allowed("settings", alerts_in_group)
    assert not allowed("abracadabra", admin)


def test_access_for_checks_chat_and_person():
    recipients = [Recipient(ADMIN, "person", "a", is_admin=True, alerts=True),
                  Recipient(GROUP, "chat", "g")]
    in_group = access_for(group_message(STRANGER, "/top")["message"], recipients)
    assert in_group == Access(STRANGER, GROUP, False, False, False, False, True)
    admin_in_private = access_for(private_message(ADMIN, "/top")["message"], recipients)
    assert admin_in_private == Access(ADMIN, ADMIN, True, True, True, True, False)
    # Чат с отрицательным id в личке не перепутать с человеком.
    other_group = access_for(group_message(ADMIN, "/top", chat=-600)["message"], recipients)
    assert other_group.known_chat is False and other_group.known_person is True
    # От имени чата: «from» — служебный бот, человека нет, а чат — свой.
    anonymous = {**group_message(ADMIN, "/top")["message"], "sender_chat": {"id": GROUP}}
    assert access_for(anonymous, recipients) == Access(None, GROUP, False, False, False, False, True)


# --- команды ---------------------------------------------------------------

def test_stranger_gets_only_id_hint():
    bot, telegram, source, _ = make_bot()
    handle(bot, private_message(STRANGER, "/top все тг"))
    texts = sent_texts(telegram)
    assert len(texts) == 1 and "\n" not in texts[0] and "/id" in texts[0]
    assert source.calls == []
    handle(bot, private_message(STRANGER, "/id"))
    assert str(STRANGER) in sent_texts(telegram)[-1]
    handle(bot, private_message(STRANGER, "/start"))
    assert str(STRANGER) in sent_texts(telegram)[-1]
    assert source.calls == []


def test_group_member_can_top():
    bot, telegram, source, _ = make_bot()
    handle(bot, group_message(STRANGER, "/top@m_ranked_bot все тг"))
    sends = telegram.of("send")
    assert len(sends) == 1 and sends[0][1] == GROUP
    assert "Лучшие посты всех вузов" in sends[0][2]
    keyboard = sends[0][3]
    assert keyboard and all(b["callback_data"].startswith("t|") for b in buttons(keyboard))
    assert "top_body" in source.calls


def test_status_refused_in_group():
    bot, telegram, _, store = make_bot()
    # MemoryStore.status_rows режет окно по настоящим часам.
    store.host_samples.append({"observed_at": datetime.now(timezone.utc) - timedelta(seconds=60),
                               "sample": {"disk": {"total": 100 * 10**9, "free": 40 * 10**9}}})
    handle(bot, group_message(ADMIN, "/status"))
    refusal = sent_texts(telegram, GROUP)
    assert len(refusal) == 1 and "Диск" not in refusal[0] and "личк" in refusal[0]
    handle(bot, private_message(PERSON, "/status"))  # человек не в списке тревог
    assert "Диск" not in sent_texts(telegram, PERSON)[-1]
    handle(bot, private_message(ADMIN, "/status"))
    rows = asyncio.run(store.status_rows(3 * 3600 + 900))
    assert rows
    assert sent_texts(telegram, ADMIN)[-1] == render_status(rows, NOW)


def test_render_status_lines():
    now = NOW
    observed = datetime.fromtimestamp(now - 60, timezone.utc)
    sample = {
        "collection": {"telegram": {"ok": 5, "failed": 1, "lastOk": now - 120},
                       "vk": {"ok": 3, "failed": 0, "lastOk": now - 4000}},
        "pipeline": {"ingestAcceptedAt": now - 60, "analysisLag": 120, "analysisBacklog": 5},
        "units": {"failed": ["m-ranked-target-web.service"]},
        "disk": {"total": 100 * 10**9, "free": 40 * 10**9},
        "memory": {"total": 100, "available": 50},
    }
    rows = [{"observed_at": datetime.fromtimestamp(now - 120, timezone.utc), "sample": {}},
            {"observed_at": observed, "sample": sample}]
    lines = render_status(rows, now).split("\n")
    assert 5 <= len(lines) <= 6
    assert lines[0].startswith("🔴") and "Сбор" in lines[0]  # MAX и Rutube без успешных циклов
    assert "Telegram 🟢" in lines[0] and "ВКонтакте 🟡" in lines[0]
    assert any(line.startswith("🟢") and "Приём с Сервера 1" in line for line in lines)
    assert any("Очередь анализа" in line and "отставание 2 мин" in line for line in lines)
    assert any(line.startswith("🔴") and "m-ranked-target-web.service" in line for line in lines)
    assert any(line.startswith("🟢") and "Диск" in line for line in lines)
    assert any(line.startswith("🟢") and "Память" in line and "50%" in line for line in lines)
    # Без снимков: строка сбора и строка о снимке, без исключения.
    empty = render_status([], now).split("\n")
    assert len(empty) == 2 and "Снимок сервера" in empty[1]


def test_callback_edits_same_message():
    bot, telegram, _, _ = make_bot()
    handle(bot, private_message(PERSON, "/top"))
    sent = telegram.of("send")[-1]
    message_id, keyboard = sent[4], sent[3]
    pressed = button_by_text(keyboard, "Все вузы")
    handle(bot, callback(PERSON, PERSON, message_id, pressed["callback_data"]))
    edits = telegram.of("edit")
    assert len(edits) == 1 and edits[0][1] == PERSON and edits[0][2] == message_id
    assert "Лучшие посты всех вузов" in edits[0][3]
    assert button_by_text(edits[0][4], "Все вузы")["text"].startswith("✓")
    assert telegram.of("answer") == [("answer", "cb1", None)]
    assert len(telegram.of("send")) == 1


def test_callback_with_long_answer_sends_new_messages():
    bot, telegram, source, _ = make_bot()
    item = fixture("findings_institution.json")["items"][0]
    body = fixture("findings_institution.json")
    body["items"] = [{**item, "platform": platform, "publicUrl": f"https://t.me/{'x' * 120}/{n}"}
                     for platform in ("telegram", "vk", "max", "rutube") for n in range(20)]
    source.body = body
    data = encode_callback(TopQuery(count=20))
    handle(bot, callback(PERSON, PERSON, 55, data))
    sends = telegram.of("send")
    assert len(sends) > 1 and telegram.of("edit") == []
    assert sends[-1][3] is not None and all(call[3] is None for call in sends[:-1])
    assert telegram.of("answer") == [("answer", "cb1", "ответ ниже")]


def test_callback_refused_for_stranger_and_stale_data():
    bot, telegram, source, _ = make_bot()
    handle(bot, callback(STRANGER, STRANGER, 55, encode_callback(TopQuery())))
    assert telegram.of("edit") == [] and source.calls == []
    assert telegram.of("answer")[-1][2]
    handle(bot, callback(PERSON, PERSON, 55, "t|garbage"))
    assert telegram.of("edit") == [] and telegram.of("answer")[-1][2]


def test_unknown_word_line():
    bot, telegram, _, _ = make_bot()
    handle(bot, private_message(PERSON, "/top абырвалг тг"))
    text = sent_texts(telegram)[-1]
    assert "не понял: абырвалг" in text and "/help" in text
    assert text.count("не понял") == 1
    assert "Наши лучшие посты · Telegram" in text


def test_top_without_slash_in_private():
    bot, telegram, _, _ = make_bot()
    handle(bot, private_message(PERSON, "топ все"))
    assert "Лучшие посты всех вузов" in sent_texts(telegram)[-1]


def test_ambiguous_institution_asks_which():
    bot, telegram, source, _ = make_bot()
    handle(bot, private_message(PERSON, "/top университет"))
    sent = telegram.of("send")[-1]
    assert "Какой" in sent[2] and "top_body" not in source.calls
    choices = [decode_callback(b["callback_data"]) for b in buttons(sent[3])]
    assert {query.institution for query in choices} == {4, 11, 12, 13}
    assert all(query.who == "institution" for query in choices)


def test_no_institution_yet():
    bot, telegram, source, _ = make_bot(our=None)
    handle(bot, private_message(PERSON, "/top"))
    assert sent_texts(telegram)[-1] == "админ ещё не выбрал наш вуз: /settings"
    assert "top_body" not in source.calls
    handle(bot, private_message(PERSON, "/top все"))  # «все» нашего вуза не требует
    assert "Лучшие посты всех вузов" in sent_texts(telegram)[-1]
    handle(bot, private_message(PERSON, "/week"))
    assert sent_texts(telegram)[-1] == "админ ещё не выбрал наш вуз: /settings"


def test_source_down_message():
    bot, telegram, source, _ = make_bot()
    source.down = True
    handle(bot, private_message(PERSON, "/top"))
    assert "данные временно недоступны" in sent_texts(telegram)[-1]
    handle(bot, private_message(PERSON, "/week"))
    assert "данные временно недоступны" in sent_texts(telegram)[-1]
    handle(bot, callback(PERSON, PERSON, 55, encode_callback(TopQuery())))
    assert telegram.of("edit") == []
    assert "данные временно недоступны" in telegram.of("answer")[-1][2]


def test_week_uses_snapshot_and_forecast():
    bot, telegram, source, store = make_bot()
    asyncio.run(store.save_week_snapshot(datetime(2026, 10, 9).date(),
                                         {"telegram": {"posts": 1, "views": 10, "reactions": 1}}))
    handle(bot, private_message(PERSON, "/week"))
    text = sent_texts(telegram)[-1]
    assert "Неделя к неделе" in text and "Первая неделя" not in text
    assert source.calls == ["dashboard", "forecast"]


def test_help_and_digest_stub():
    bot, telegram, _, _ = make_bot()
    handle(bot, private_message(ADMIN, "/help"))
    assert "/settings" in sent_texts(telegram)[-1] and "/status" in sent_texts(telegram)[-1]
    handle(bot, group_message(ADMIN, "/help"))
    assert "/settings" not in sent_texts(telegram, GROUP)[-1]
    handle(bot, private_message(PERSON, "/help"))
    assert "/status" not in sent_texts(telegram, PERSON)[-1]
    handle(bot, group_message(STRANGER, "/digest"))
    assert sent_texts(telegram, GROUP)[-1] == "дайджест появится после подключения расписания"

    seen = []

    async def digest_here(chat_id: int) -> None:
        seen.append(chat_id)

    bot.send_digest_here = digest_here
    handle(bot, group_message(STRANGER, "/digest"))
    assert seen == [GROUP]


# --- чаты ------------------------------------------------------------------

def membership(by: int, chat: int, old: str, new: str) -> dict:
    return {"update_id": 3, "my_chat_member": {
        "chat": {"id": chat, "type": "supergroup", "title": "Команда"},
        "from": {"id": by}, "date": 1,
        "old_chat_member": {"user": {"id": 1, "is_bot": True}, "status": old},
        "new_chat_member": {"user": {"id": 1, "is_bot": True}, "status": new}}}


def test_added_by_admin_registers_chat():
    bot, telegram, _, store = make_bot(recipients=[Recipient(ADMIN, "person", "a", is_admin=True)])
    handle(bot, membership(ADMIN, -700, "left", "member"))
    chats = [r for r in asyncio.run(store.recipients()) if r.kind == "chat"]
    assert chats == [Recipient(-700, "chat", "Команда", digest=True, spike=True, anomaly=True)]
    assert telegram.of("leave") == []

    handle(bot, membership(STRANGER, -800, "left", "member"))
    assert telegram.of("leave") == [("leave", -800)]
    assert all(r.chat_id != -800 for r in asyncio.run(store.recipients()))

    # Повышение в уже подключённом чате (даже не админом) не сбрасывает флаги и не уводит бота.
    asyncio.run(store.upsert_recipient(Recipient(-700, "chat", "Команда", digest=False), None))
    handle(bot, membership(STRANGER, -700, "member", "administrator"))
    assert telegram.of("leave") == [("leave", -800)]
    assert [r for r in asyncio.run(store.recipients()) if r.chat_id == -700][0].digest is False

    handle(bot, membership(STRANGER, -700, "member", "kicked"))
    assert all(r.chat_id != -700 for r in asyncio.run(store.recipients()))


def test_leave_chat_error_is_swallowed():
    bot, telegram, _, _ = make_bot()

    async def leave_fails(chat_id):
        raise TelegramError("leaveChat: Telegram ответил 403: Forbidden")

    telegram.leave_chat = leave_fails
    handle(bot, membership(STRANGER, -800, "left", "member"))


def test_migrate_to_supergroup():
    bot, _, _, store = make_bot()
    update = {"update_id": 4, "message": {"message_id": 9, "chat": {"id": GROUP, "type": "group"},
                                          "from": {"id": ADMIN}, "migrate_to_chat_id": -100500}}
    handle(bot, update)
    chats = {r.chat_id: r for r in asyncio.run(store.recipients()) if r.kind == "chat"}
    assert set(chats) == {-100500} and chats[-100500].spike is True


# --- рассылка --------------------------------------------------------------

def test_blocked_recipient_removed():
    bot, telegram, _, store = make_bot(recipients=[
        Recipient(10, "person", "a", digest=True), Recipient(11, "person", "b", digest=True),
        Recipient(12, "person", "c", digest=True), Recipient(13, "person", "d"),
        Recipient(-14, "chat", "g", digest=True)])
    telegram.blocked = {11}
    telegram.failing = {12}
    count = asyncio.run(bot.broadcast([Message("часть 1"), Message("часть 2")], "digest"))
    assert count == 2
    assert {call[1] for call in telegram.of("send")} == {10, -14}
    assert len(telegram.of("send")) == 4
    remaining = {r.chat_id for r in asyncio.run(store.recipients())}
    assert remaining == {10, 12, 13, -14}


def test_alerts_broadcast_only_to_people():
    bot, telegram, _, store = make_bot(recipients=[Recipient(10, "person", "a", alerts=True),
                                                   Recipient(11, "person", "b")])
    # Чат с alerts=True в обход Recipient: рассылка тревог его всё равно не видит.
    chat = Recipient(-14, "chat", "g")
    chat.alerts = True
    people = asyncio.run(store.recipients())

    async def recipients():  # MemoryStore такую запись не отдаст: подменяем чтение
        return people + [chat]

    store.recipients = recipients
    assert asyncio.run(bot.broadcast("тревога", "alerts")) == 1
    assert [call[1] for call in telegram.of("send")] == [10]
    with pytest.raises(ValueError):
        asyncio.run(bot.broadcast("x", "everything"))


# --- настройки -------------------------------------------------------------

def press(bot: Bot, telegram: FakeTelegram, user: int, fragment: str, keyboard=None) -> None:
    if keyboard is None:
        keyboard = last_screen(telegram)[1]
    handle(bot, callback(user, user, 77, button_by_text(keyboard, fragment)["callback_data"]))


def last_screen(telegram: FakeTelegram) -> tuple[str, list[list[dict]] | None]:
    for call in reversed(telegram.calls):
        if call[0] == "send":
            return call[2], call[3]
        if call[0] == "edit":
            return call[3], call[4]
    raise AssertionError("ничего не отправлено")


def test_settings_flow():
    bot, telegram, _, store = make_bot(our=None)
    handle(bot, private_message(ADMIN, "/settings"))
    text, keyboard = last_screen(telegram)
    assert "Настройки" in text
    assert all(b["callback_data"].startswith("s|") for b in buttons(keyboard))

    # Наш вуз: название, неоднозначное → кнопка выбора.
    press(bot, telegram, ADMIN, "Наш вуз")
    assert bot.pending[ADMIN]
    handle(bot, private_message(ADMIN, "университет"))
    text, keyboard = last_screen(telegram)
    assert "Какой" in text and len(buttons(keyboard)) >= 4
    press(bot, telegram, ADMIN, "Дельта")
    assert asyncio.run(store.get_setting(OUR_INSTITUTION)) == OUR_ID
    assert ADMIN not in bot.pending
    assert "Дельта" in last_screen(telegram)[0]

    # Однозначное название сохраняется сразу.
    press(bot, telegram, ADMIN, "Наш вуз", keyboard=[[{"text": "Наш вуз", "callback_data": "s|our"}]])
    handle(bot, private_message(ADMIN, "Бета"))
    assert asyncio.run(store.get_setting(OUR_INSTITUTION)) == 12

    # Человек по ID, затем тревоги ему.
    press(bot, telegram, ADMIN, "Люди", keyboard=[[{"text": "Люди", "callback_data": "s|people"}]])
    press(bot, telegram, ADMIN, "Добавить")
    handle(bot, private_message(ADMIN, "31"))
    added = {r.chat_id: r for r in asyncio.run(store.recipients())}[31]
    assert added.kind == "person" and not added.alerts
    press(bot, telegram, ADMIN, "Тревоги")
    added = {r.chat_id: r for r in asyncio.run(store.recipients())}[31]
    assert added.alerts is True
    # Человек из списка тревог получает /status в меню.
    assert ("commands", ["top", "week", "digest", "help", "id", "status"],
            {"type": "chat", "chat_id": 31}) in telegram.of("commands")

    # Пересланное сообщение тоже добавляет человека.
    press(bot, telegram, ADMIN, "Добавить", keyboard=[[{"text": "Добавить", "callback_data": "s|add"}]])
    handle(bot, private_message(ADMIN, "привет", forward_origin={
        "type": "user", "date": 1, "sender_user": {"id": 32, "first_name": "Пётр"}}))
    assert {r.chat_id: r for r in asyncio.run(store.recipients())}[32].title == "Пётр"

    # Рабочий чат: переключатели без тревог.
    press(bot, telegram, ADMIN, "Рабочий чат", keyboard=[[{"text": "Рабочий чат", "callback_data": "s|chats"}]])
    text, keyboard = last_screen(telegram)
    assert "рабочий чат" in text
    labels = " ".join(b["text"] for b in buttons(keyboard))
    assert "Дайджест" in labels and "Тревог" not in labels
    press(bot, telegram, ADMIN, "Дайджест")
    assert {r.chat_id: r for r in asyncio.run(store.recipients())}[GROUP].digest is False
    # Подделанная кнопка тревог для чата ничего не включает.
    handle(bot, callback(ADMIN, ADMIN, 77, f"s|pt|{GROUP}|t"))
    assert {r.chat_id: r for r in asyncio.run(store.recipients())}[GROUP].alerts is False
    with pytest.raises(ValueError):
        Recipient(GROUP, "chat", "g", alerts=True)


def test_settings_refused_for_non_admin_and_in_group():
    bot, telegram, _, store = make_bot()
    handle(bot, private_message(PERSON, "/settings"))
    assert sent_texts(telegram, PERSON)[-1] == "Настройки — только админу бота и только в личке."
    handle(bot, group_message(ADMIN, "/settings"))
    assert sent_texts(telegram, GROUP)[-1] == "Настройки — только админу бота и только в личке."
    handle(bot, callback(PERSON, PERSON, 77, f"s|pt|{PERSON}|x"))
    assert {r.chat_id: r for r in asyncio.run(store.recipients())}[PERSON].is_admin is False


def test_my_notifications_and_person_removal():
    bot, telegram, _, store = make_bot()
    handle(bot, private_message(ADMIN, "/settings"))
    press(bot, telegram, ADMIN, "Мои уведомления")
    text, keyboard = last_screen(telegram)
    labels = " ".join(b["text"] for b in buttons(keyboard))
    assert "Убрать" not in labels and "Админ" not in labels  # себя не убрать и прав не лишить
    press(bot, telegram, ADMIN, "Дайджест")
    assert {r.chat_id: r for r in asyncio.run(store.recipients())}[ADMIN].digest is True

    handle(bot, callback(ADMIN, ADMIN, 77, f"s|p|{PERSON}"))
    press(bot, telegram, ADMIN, "Убрать")
    assert PERSON not in {r.chat_id for r in asyncio.run(store.recipients())}
    assert ("commands", ["top", "week", "digest", "help", "id"],
            {"type": "chat", "chat_id": PERSON}) in telegram.of("commands")


def test_bad_person_id_keeps_waiting():
    bot, telegram, _, _ = make_bot()
    handle(bot, callback(ADMIN, ADMIN, 77, "s|add"))
    handle(bot, private_message(ADMIN, "не число"))
    assert bot.pending.get(ADMIN) and "ID" in sent_texts(telegram, ADMIN)[-1]
    handle(bot, private_message(ADMIN, "/help"))  # команда отменяет ожидание
    assert ADMIN not in bot.pending


def test_mute_callback_default_hook():
    bot, telegram, _, _ = make_bot()
    handle(bot, callback(ADMIN, ADMIN, 77, "m|disk"))
    assert telegram.of("answer") == [("answer", "cb1", "недоступно")]


# --- запуск ----------------------------------------------------------------

def test_setup_commands_scopes():
    bot, telegram, _, store = make_bot(recipients=[
        Recipient(ADMIN, "person", "старое имя", digest=True),
        Recipient(PERSON, "person", "человек", alerts=True),
        Recipient(22, "person", "без тревог"),
        Recipient(GROUP, "chat", "g", digest=True)])
    bot.config = replace(bot.config, admin_ids=frozenset({ADMIN, 8}))
    asyncio.run(bot.setup())
    people = {r.chat_id: r for r in asyncio.run(store.recipients())}
    assert people[8] == Recipient(8, "person", "8", is_admin=True, alerts=True)
    # Уже записанный админ: флаги сохраняются, права админа — принудительно.
    assert people[ADMIN].is_admin is True and people[ADMIN].digest is True
    assert people[ADMIN].title == "старое имя"
    base = ["top", "week", "digest", "help", "id"]
    commands = telegram.of("commands")
    assert ("commands", base, {"type": "default"}) in commands
    assert ("commands", base, {"type": "all_group_chats"}) in commands
    assert ("commands", base + ["status"], {"type": "chat", "chat_id": PERSON}) in commands
    assert ("commands", base + ["status", "settings"], {"type": "chat", "chat_id": 8}) in commands
    # Меню совпадает с allowed(): админ, выключивший себе тревоги, /status не видит.
    assert ("commands", base + ["settings"], {"type": "chat", "chat_id": ADMIN}) in commands
    assert not any(scope == {"type": "chat", "chat_id": 22} for _, _, scope in commands)
    assert not any(scope.get("chat_id") == GROUP for _, _, scope in commands)
