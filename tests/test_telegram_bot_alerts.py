"""Доставка тревог из очереди: тихие часы, заглушка, утренняя сводка."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from telegram_bot import alerts_inbox
from telegram_bot.alerts_inbox import alert_text, deliver, install, is_quiet, morning, read_inbox
from telegram_bot.config import BotConfig
from telegram_bot.handlers import Bot
from telegram_bot.store import MemoryStore, Recipient
from telegram_bot.telegram import BotBlocked, CannotInitiate, TelegramError

ADMIN = 7
PERSON = 21
GROUP = -500
MSK = ZoneInfo("Europe/Moscow")
NOON = datetime(2026, 10, 16, 12, 0, tzinfo=MSK)
NIGHT = datetime(2026, 10, 17, 3, 0, tzinfo=MSK)
MORNING = datetime(2026, 10, 17, 8, 0, tzinfo=MSK)

SCRIPT = Path(__file__).parents[1] / "operations" / "scripts" / "alerts.py"


class FakeTelegram:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.failing: set[int] = set()
        self._next_id = 100

    def of(self, name: str) -> list[tuple]:
        return [call for call in self.calls if call[0] == name]

    async def send_message(self, chat_id, text, keyboard=None):
        if chat_id in self.failing:
            raise TelegramError("sendMessage: Telegram ответил 500")
        self._next_id += 1
        self.calls.append(("send", chat_id, text, keyboard, self._next_id))
        return {"message_id": self._next_id, "chat": {"id": chat_id}}

    async def edit_message(self, chat_id, message_id, text, keyboard=None):
        self.calls.append(("edit", chat_id, message_id, text, keyboard))

    async def answer_callback(self, callback_id, text=None):
        self.calls.append(("answer", callback_id, text))


def make_bot(tmp_path: Path, *, recipients: list[Recipient] | None = None, now: datetime = NOON):
    telegram, store = FakeTelegram(), MemoryStore()
    config = BotConfig(token="test-token", admin_ids=frozenset({ADMIN}), api_base_url="http://api.test",
                       dsn="postgresql://test", spool_dir=tmp_path)
    bot = Bot(telegram, None, store, config, clock=lambda: now.timestamp())  # type: ignore[arg-type]
    install(bot)

    async def seed() -> None:
        for recipient in recipients if recipients is not None else [
            Recipient(ADMIN, "person", "админ", is_admin=True, alerts=True),
            Recipient(PERSON, "person", "человек", digest=True),
            Recipient(GROUP, "chat", "рабочий чат", digest=True),
        ]:
            await store.upsert_recipient(recipient, None)

    asyncio.run(seed())
    return bot, telegram, store


def spool(tmp_path: Path, key: str = "disk", kind: str = "open", *, urgent: bool = False,
          text: str = "диск заполнен", server: str = "Сервер 2", since: float = 1_000_000.0,
          stamp: int | None = None, at: float | None = None) -> Path:
    stamp = stamp if stamp is not None else time.time_ns()
    path = tmp_path / f"{stamp}-{key}.json"
    path.write_text(json.dumps({"version": 1, "server": server, "key": key, "kind": kind, "urgent": urgent,
                                "text": text, "since": since,
                                "at": NIGHT.timestamp() - 60 if at is None else at}), encoding="utf-8")
    return path


def files(tmp_path: Path) -> list[str]:
    return sorted(path.name for path in tmp_path.glob("*.json"))


# --- чтение очереди ----------------------------------------------------------

def test_read_inbox_orders_by_name_and_skips_temporaries(tmp_path):
    second = spool(tmp_path, "b", stamp=2)
    first = spool(tmp_path, "a", stamp=1)
    (tmp_path / ".3-c.json.tmp").write_text("{", encoding="utf-8")
    (tmp_path / ".hidden.json").write_text("{}", encoding="utf-8")
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    assert [path for path, _ in read_inbox(tmp_path)] == [first, second]
    assert read_inbox(tmp_path)[0][1]["key"] == "a"
    assert (tmp_path / ".3-c.json.tmp").exists()


def test_read_inbox_removes_stale_temporaries_only(tmp_path):
    stale, fresh = tmp_path / ".1-a.json.tmp", tmp_path / ".2-b.json.tmp"
    stale.write_text("{", encoding="utf-8")
    fresh.write_text("{", encoding="utf-8")
    old = time.time() - 2 * 3600
    os.utime(stale, (old, old))
    assert read_inbox(tmp_path) == []
    assert not stale.exists() and fresh.exists()


def test_read_inbox_deletes_broken_files_and_logs_class_only(tmp_path, caplog):
    broken = tmp_path / "1-x.json"
    broken.write_text('{"секретный текст', encoding="utf-8")
    wrong = tmp_path / "2-y.json"
    wrong.write_text(json.dumps({"version": 2, "server": "s", "key": "y", "kind": "open", "text": "t"}),
                     encoding="utf-8")
    incomplete = tmp_path / "3-z.json"
    incomplete.write_text(json.dumps({"version": 1, "server": "s", "key": "z", "kind": "bogus", "text": "t"}),
                          encoding="utf-8")
    good = spool(tmp_path, "g", stamp=4)
    with caplog.at_level("INFO"):
        assert [path for path, _ in read_inbox(tmp_path)] == [good]
    assert files(tmp_path) == [good.name]
    assert "секретный" not in caplog.text
    assert caplog.text


def test_read_inbox_missing_directory(tmp_path):
    assert read_inbox(tmp_path / "нет") == []


# --- тихие часы ---------------------------------------------------------------

@pytest.mark.parametrize("hour,minute,quiet", [(22, 59, False), (23, 0, True), (0, 0, True),
                                               (7, 59, True), (8, 0, False), (12, 0, False)])
def test_quiet_boundaries(hour, minute, quiet):
    assert is_quiet(datetime(2026, 10, 17, hour, minute, tzinfo=MSK)) is quiet


def test_quiet_uses_moscow_time_for_other_zones():
    assert is_quiet(datetime(2026, 10, 17, 0, 30, tzinfo=timezone.utc))  # 03:30 MSK
    assert not is_quiet(datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc))  # 12:00 MSK


def test_day_alert_is_sent_and_file_removed(tmp_path):
    bot, telegram, store = make_bot(tmp_path)
    spool(tmp_path)
    asyncio.run(deliver(bot, datetime(2026, 10, 16, 22, 59, tzinfo=MSK)))
    assert [call[1] for call in telegram.of("send")] == [ADMIN]
    assert files(tmp_path) == []
    assert asyncio.run(store.take_held()) == []


def test_quiet_nonurgent_is_held_not_sent(tmp_path):
    bot, telegram, store = make_bot(tmp_path)
    spool(tmp_path)
    asyncio.run(deliver(bot, datetime(2026, 10, 16, 23, 0, tzinfo=MSK)))
    assert telegram.of("send") == []
    assert files(tmp_path) == []
    assert [event["key"] for event in asyncio.run(store.take_held())] == ["disk"]


def test_urgent_breaks_quiet(tmp_path):
    bot, telegram, store = make_bot(tmp_path)
    spool(tmp_path, urgent=True, text="сервер не отвечает")
    asyncio.run(deliver(bot, NIGHT))
    assert len(telegram.of("send")) == 1
    assert "сервер не отвечает" in telegram.of("send")[0][2]
    assert asyncio.run(store.take_held()) == []


def test_alert_text_is_html_escaped_on_the_wire(tmp_path):
    bot, telegram, _ = make_bot(tmp_path)
    spool(tmp_path, text="p95 < 3 & выше")
    asyncio.run(deliver(bot, NOON))
    assert "p95 &lt; 3 &amp; выше" in telegram.of("send")[0][2]


# --- заглушка -----------------------------------------------------------------

def test_mute_drops_open_and_repeat_not_resolve(tmp_path):
    bot, telegram, store = make_bot(tmp_path)
    asyncio.run(store.set_mute("disk", time.time() + 3600, ADMIN))
    spool(tmp_path, "disk", "open", stamp=1)
    spool(tmp_path, "disk", "repeat", stamp=2)
    asyncio.run(deliver(bot, NOON))
    assert telegram.of("send") == []
    assert files(tmp_path) == []
    spool(tmp_path, "disk", "resolve", text="диск освободился", stamp=3)
    asyncio.run(deliver(bot, NOON))
    assert len(telegram.of("send")) == 1
    assert "Прошло" in telegram.of("send")[0][2]
    spool(tmp_path, "load", "open", text="нагрузка", stamp=4)
    asyncio.run(deliver(bot, NOON))
    assert len(telegram.of("send")) == 2


def test_muted_nonurgent_open_at_night_is_not_held(tmp_path):
    bot, telegram, store = make_bot(tmp_path)
    asyncio.run(store.set_mute("disk", time.time() + 3600, ADMIN))
    spool(tmp_path, "disk", "open")
    asyncio.run(deliver(bot, NIGHT))
    assert asyncio.run(store.take_held()) == []


def callback(user: int, key: str, text: str, *, chat_type: str = "private", chat_id: int | None = None) -> dict:
    return {"update_id": 1, "callback_query": {
        "id": "cb1", "from": {"id": user}, "data": f"m|{key}",
        "message": {"message_id": 55, "chat": {"id": chat_id if chat_id is not None else user, "type": chat_type},
                    "text": text}}}


def test_mute_button_on_open_and_repeat_not_resolve(tmp_path):
    bot, telegram, _ = make_bot(tmp_path)
    spool(tmp_path, "disk", "open", stamp=1)
    spool(tmp_path, "disk", "repeat", stamp=2)
    spool(tmp_path, "disk", "resolve", stamp=3)
    asyncio.run(deliver(bot, NOON))
    sent = telegram.of("send")
    assert [call[3] is not None for call in sent] == [True, True, False]
    assert sent[0][3] == [[{"text": "🔕 Заглушить на 2 часа", "callback_data": "m|disk"}]]


def test_long_key_gets_no_button(tmp_path):
    bot, telegram, _ = make_bot(tmp_path)
    long_key = "k" * 50
    spool(tmp_path, long_key, "open")
    asyncio.run(deliver(bot, NOON))
    assert telegram.of("send")[0][3] is not None
    telegram.calls.clear()
    # «m|» + ключ > 64 байт: кнопку не ставим, а тревога всё равно уходит.
    spool(tmp_path, "k" * 63, "open")
    asyncio.run(deliver(bot, NOON))
    assert len(telegram.of("send")) == 1
    assert telegram.of("send")[0][3] is None


def test_mute_button_press_sets_mute_and_edits_message(tmp_path):
    bot, telegram, store = make_bot(tmp_path)
    asyncio.run(bot.handle(callback(ADMIN, "disk", "m-ranked · Сервер 2\n🔴 диск < 5%")))
    assert store._mutes["disk"] == NOON.timestamp() + 7200
    edit = telegram.of("edit")[0]
    assert edit[1:3] == (ADMIN, 55)
    assert edit[3] == "m-ranked · Сервер 2\n🔴 диск &lt; 5%\n🔕 заглушено до 14:00"
    assert edit[4] is None
    assert telegram.of("answer") == [("answer", "cb1", "заглушено на 2 часа")]


def test_mute_button_refused_for_non_alert_person_and_groups(tmp_path):
    bot, telegram, store = make_bot(tmp_path)
    asyncio.run(bot.handle(callback(PERSON, "disk", "t")))
    asyncio.run(bot.handle(callback(ADMIN, "disk", "t", chat_type="supergroup", chat_id=GROUP)))
    assert store._mutes == {}
    assert telegram.of("edit") == []
    assert len(telegram.of("answer")) == 2


def test_mute_button_bad_key_is_answered(tmp_path):
    bot, telegram, store = make_bot(tmp_path)
    asyncio.run(bot.handle(callback(ADMIN, "", "t")))
    assert store._mutes == {}
    assert len(telegram.of("answer")) == 1


# --- утренняя сводка ----------------------------------------------------------

def test_morning_collapses_night(tmp_path):
    bot, telegram, store = make_bot(tmp_path)
    for stamp, (key, kind, text) in enumerate([
        ("disk", "open", "диск заполнен"), ("load", "open", "нагрузка высокая"),
        ("disk", "repeat", "диск заполнен"), ("disk", "resolve", "диск заполнен"),
        ("load", "repeat", "нагрузка высокая"),
    ], start=1):
        spool(tmp_path, key, kind, text=text, stamp=stamp)
    asyncio.run(deliver(bot, NIGHT))
    assert telegram.of("send") == []
    asyncio.run(morning(bot, MORNING))
    sent = telegram.of("send")
    assert len(sent) == 1
    text = sent[0][2]
    assert text.count("за ночь открылась и закрылась") == 1
    assert "за ночь открылась и закрылась: диск заполнен" in text
    assert "🔴 Всё ещё: нагрузка высокая" in text
    assert text.count("нагрузка высокая") == 1
    assert text.count("диск заполнен") == 1
    assert asyncio.run(store.take_held()) == []


def test_morning_resolve_without_open_and_other_servers(tmp_path):
    bot, telegram, _ = make_bot(tmp_path)
    spool(tmp_path, "disk", "resolve", text="диск освободился", stamp=1)
    spool(tmp_path, "disk", "open", text="диск на втором", server="Сервер 1", stamp=2)
    asyncio.run(deliver(bot, NIGHT))
    asyncio.run(morning(bot, MORNING))
    text = telegram.of("send")[0][2]
    assert "🟢 Прошло: диск освободился" in text
    assert "Сервер 1" in text and "Сервер 2" in text
    assert "закрылась" not in text


def test_morning_sends_nothing_when_nothing_held(tmp_path):
    bot, telegram, _ = make_bot(tmp_path)
    asyncio.run(morning(bot, MORNING))
    assert telegram.of("send") == []


def test_morning_failure_puts_events_back(tmp_path):
    bot, telegram, store = make_bot(tmp_path)
    spool(tmp_path, "disk", "open")
    asyncio.run(deliver(bot, NIGHT))
    telegram.failing = {ADMIN}
    asyncio.run(morning(bot, MORNING))
    assert telegram.of("send") == []
    telegram.failing = set()
    asyncio.run(morning(bot, MORNING))
    assert len(telegram.of("send")) == 1


def test_morning_without_recipients_drops_events(tmp_path):
    bot, telegram, store = make_bot(tmp_path, recipients=[Recipient(PERSON, "person", "человек")])
    asyncio.run(store.hold_alert({"version": 1, "server": "s", "key": "k", "kind": "open", "urgent": False,
                                  "text": "t", "since": 1.0, "at": MORNING.timestamp() - 60}))
    asyncio.run(morning(bot, MORNING))
    assert telegram.of("send") == []
    assert asyncio.run(store.take_held()) == []


# --- сбои и получатели --------------------------------------------------------

def test_send_failure_keeps_file(tmp_path):
    bot, telegram, _ = make_bot(tmp_path)
    telegram.failing = {ADMIN}
    path = spool(tmp_path)
    asyncio.run(deliver(bot, NOON))
    assert path.exists()
    telegram.failing = set()
    asyncio.run(deliver(bot, NOON))
    assert not path.exists()
    assert len(telegram.of("send")) == 1


def test_failure_keeps_order_by_stopping_at_first_failed_file(tmp_path):
    bot, telegram, _ = make_bot(tmp_path)
    telegram.failing = {ADMIN}
    first = spool(tmp_path, "a", "open", stamp=1)
    second = spool(tmp_path, "a", "resolve", stamp=2)
    asyncio.run(deliver(bot, NOON))
    assert first.exists() and second.exists()


def test_undeliverable_fresh_file_is_kept_but_stale_one_is_dropped(tmp_path):
    bot, telegram, _ = make_bot(tmp_path)
    telegram.failing = {ADMIN}
    fresh = spool(tmp_path, "a", "open", stamp=1, at=NOON.timestamp() - 5 * 3600)
    asyncio.run(deliver(bot, NOON))
    assert fresh.exists()
    stale = spool(tmp_path, "b", "open", stamp=2, at=NOON.timestamp() - 6 * 3600 - 1)
    telegram.failing = set()
    asyncio.run(deliver(bot, NOON))
    assert not stale.exists()
    assert [call[2].count("диск") for call in telegram.of("send")] == [1]  # ушёл только свежий
    assert not fresh.exists()


def test_stale_file_is_dropped_without_sending_and_logs_name_only(tmp_path, caplog):
    bot, telegram, store = make_bot(tmp_path)
    stale = spool(tmp_path, "a", "resolve", text="секретный текст", at=NOON.timestamp() - 7 * 3600)
    with caplog.at_level("INFO"):
        asyncio.run(deliver(bot, NOON))
    assert not stale.exists()
    assert telegram.of("send") == []
    assert asyncio.run(store.take_held()) == []
    assert "stale" in caplog.text and "секретный" not in caplog.text


def test_morning_rehold_drops_events_older_than_a_day(tmp_path):
    bot, telegram, store = make_bot(tmp_path)
    telegram.failing = {ADMIN}
    base = {"version": 1, "server": "s", "kind": "open", "urgent": False, "text": "t", "since": 1.0}
    asyncio.run(store.hold_alert({**base, "key": "old", "at": MORNING.timestamp() - 24 * 3600 - 1}))
    asyncio.run(store.hold_alert({**base, "key": "new", "at": MORNING.timestamp() - 3600}))
    asyncio.run(morning(bot, MORNING))
    assert [event["key"] for event in asyncio.run(store.take_held())] == ["new"]


def test_no_alert_recipients_deletes_file(tmp_path):
    bot, telegram, store = make_bot(tmp_path, recipients=[Recipient(PERSON, "person", "человек")])
    path = spool(tmp_path)
    asyncio.run(deliver(bot, NOON))
    assert not path.exists()
    assert telegram.of("send") == []


def test_chats_never_get_alerts(tmp_path):
    bot, telegram, store = make_bot(tmp_path)
    chat = Recipient(GROUP, "chat", "рабочий чат")
    chat.alerts = True  # в обход Recipient
    people = asyncio.run(store.recipients())

    async def recipients():
        return people + [chat]

    store.recipients = recipients
    spool(tmp_path)
    asyncio.run(deliver(bot, NOON))
    assert [call[1] for call in telegram.of("send")] == [ADMIN]


def test_only_chat_with_alerts_flag_is_treated_as_no_recipients(tmp_path):
    bot, telegram, store = make_bot(tmp_path, recipients=[Recipient(PERSON, "person", "человек")])
    chat = Recipient(GROUP, "chat", "рабочий чат")
    chat.alerts = True
    people = asyncio.run(store.recipients())

    async def recipients():
        return people + [chat]

    store.recipients = recipients
    path = spool(tmp_path)
    asyncio.run(deliver(bot, NOON))
    assert telegram.of("send") == []
    assert not path.exists()


# --- формат текста совпадает со скриптом тревог -------------------------------

def load_alerts_script():
    spec = importlib.util.spec_from_file_location("alerts_for_bot_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["alerts_for_bot_test"] = module  # dataclass ищет модуль по имени
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("kind", ["open", "repeat", "resolve"])
def test_alert_text_matches_alerts_script(kind, monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Moscow")
    time.tzset()
    try:
        alerts = load_alerts_script()
        since = datetime(2026, 10, 16, 21, 5, tzinfo=MSK).timestamp()
        event = alerts.Event(key="disk", kind=kind, urgent=False, text="диск заполнен", since=since)
        payload = {"version": 1, "server": "Сервер 2", "key": "disk", "kind": kind, "urgent": False,
                   "text": "диск заполнен", "since": since, "at": since}
        assert alert_text(payload) == "m-ranked · Сервер 2\n" + alerts.format_event(event)
    finally:
        monkeypatch.undo()
        time.tzset()
    if kind == "repeat":
        assert alert_text(payload).endswith("(с 16.10 21:05)")
