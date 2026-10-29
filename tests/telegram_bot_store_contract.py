"""Общий контракт хранилища бота: одни и те же проверки для MemoryStore и PostgresStore.

Модуль не собирается pytest (имя без test_); сценарии запускают
test_telegram_bot_store.py и test_telegram_bot_store_postgres.py. Каждый сценарий
получает окружение: store и seed_host_sample — подкладывание снимка ресурсов,
которое сам бот делать не умеет (он только читает host_sample).
"""
from __future__ import annotations

import time
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from telegram_bot.store import Recipient

DAY = 86400.0


def _uuid() -> str:
    return str(uuid.uuid4())


async def chat_alerts_rejected(env) -> None:
    with pytest.raises(ValueError):
        Recipient(chat_id=-1, kind="chat", title="чат", alerts=True)
    with pytest.raises(ValueError):
        Recipient(chat_id=-1, kind="chat", title="чат", is_admin=True)
    with pytest.raises(ValueError):
        Recipient(chat_id=1, kind="channel", title="канал")
    Recipient(chat_id=-1, kind="chat", title="чат", digest=True, spike=True, anomaly=True)
    Recipient(chat_id=1, kind="person", title="я", is_admin=True, alerts=True)
    assert await env.store.recipients() == []


async def recipients_roundtrip(env) -> None:
    store = env.store
    await store.upsert_recipient(Recipient(30, "person", "Вера", is_admin=True, alerts=True, digest=True), by=7)
    await store.upsert_recipient(Recipient(-10, "chat", "Чат", spike=True), by=None)
    assert await store.recipients() == [
        Recipient(-10, "chat", "Чат", spike=True),
        Recipient(30, "person", "Вера", is_admin=True, alerts=True, digest=True),
    ]
    await store.upsert_recipient(Recipient(30, "person", "Вера К.", anomaly=True), by=7)
    people = [r for r in await store.recipients() if r.chat_id == 30]
    assert people == [Recipient(30, "person", "Вера К.", anomaly=True)]
    await store.remove_recipient(30)
    await store.remove_recipient(30)
    assert [r.chat_id for r in await store.recipients()] == [-10]


async def announce_dedup_and_level_up(env) -> None:
    store = env.store
    pid = _uuid()
    assert await store.has_announced_any("spike") is False
    assert await store.mark_announced("spike", pid, 2) is True
    assert await store.mark_announced("spike", pid, 2) is False
    assert await store.mark_announced("spike", pid, 1) is False
    assert await store.mark_announced("spike", pid, 3) is True
    assert await store.mark_announced("spike", pid, 3) is False
    assert await store.mark_announced("anomaly", pid, 2) is True
    assert await store.has_announced_any("spike") is True
    assert await store.has_announced_any("digest") is False
    # Забыть можно только тот уровень, что отмечен: чужую отметку не снимаем.
    await store.forget_announced("spike", pid, 2)
    assert await store.mark_announced("spike", pid, 3) is False
    await store.forget_announced("spike", pid, 3)
    assert await store.mark_announced("spike", pid, 1) is True


async def take_held_empties(env) -> None:
    store = env.store
    assert await store.take_held() == []
    first = {"kind": "anomaly", "level": 3, "title": "Всплеск", "nested": {"a": [1, 2]}}
    second = {"kind": "spike", "level": 2}
    await store.hold_alert(first)
    await store.hold_alert(second)
    assert await store.take_held() == [first, second]
    assert await store.take_held() == []


async def migrate_chat_keeps_flags(env) -> None:
    store = env.store
    await store.upsert_recipient(Recipient(-100, "chat", "Группа", digest=True, spike=True, anomaly=True), by=1)
    await store.migrate_chat(-100, -1000)
    assert await store.recipients() == [
        Recipient(-1000, "chat", "Группа", digest=True, spike=True, anomaly=True)]
    # Миграция на уже существующий чат не падает: старая запись просто уходит.
    await store.upsert_recipient(Recipient(-7, "chat", "Старая"), by=1)
    await store.migrate_chat(-7, -1000)
    assert [r.chat_id for r in await store.recipients()] == [-1000]
    # Несуществующий чат — не ошибка.
    await store.migrate_chat(-555, -556)
    assert [r.chat_id for r in await store.recipients()] == [-1000]


async def prune_drops_old(env) -> None:
    store = env.store
    now = time.time()
    pid = _uuid()
    assert await store.mark_announced("spike", pid, 2) is True
    today = datetime.now(UTC).date()
    old_day, fresh_day = today - timedelta(days=40), today - timedelta(days=5)
    await store.save_week_snapshot(old_day, {"posts": 1})
    await store.save_week_snapshot(fresh_day, {"posts": 2})
    await store.set_mute("anomaly:L2", now + 1000, by=1)

    await store.prune(now)
    assert await store.mark_announced("spike", pid, 2) is False
    assert await store.week_snapshot(old_day) is None
    assert await store.week_snapshot(fresh_day) == {"posts": 2}
    assert await store.muted_until("anomaly:L2") is not None

    await store.prune(now + 61 * DAY)
    assert await store.mark_announced("spike", pid, 2) is True
    assert await store.week_snapshot(fresh_day) is None
    assert await store.muted_until("anomaly:L2") is None


async def mute_expiry(env) -> None:
    store = env.store
    now = time.time()
    assert await store.muted_until("spike") is None
    await store.set_mute("spike", now + 600, by=5)
    until = await store.muted_until("spike")
    assert until == pytest.approx(now + 600, abs=1e-3)
    await store.set_mute("spike", now - 5, by=5)
    assert await store.muted_until("spike") is None
    await store.set_mute("spike", now + 60, by=6)
    assert await store.muted_until("spike") == pytest.approx(now + 60, abs=1e-3)


async def settings_roundtrip(env) -> None:
    store = env.store
    assert await store.get_setting("our_institution") is None
    await store.set_setting("our_institution", 12345, by=1)
    assert await store.get_setting("our_institution") == 12345
    await store.set_setting("our_institution", 7, by=2)
    assert await store.get_setting("our_institution") == 7
    await store.set_setting("complex", {"a": [1, "б", None], "b": {"c": True}}, by=2)
    assert await store.get_setting("complex") == {"a": [1, "б", None], "b": {"c": True}}
    await store.set_setting("spike_seeded_for", 7, by=None)  # пишет сам бот, не админ
    assert await store.get_setting("spike_seeded_for") == 7


async def week_snapshot_roundtrip(env) -> None:
    store = env.store
    day = date(2026, 10, 12)
    assert await store.week_snapshot(day) is None
    await store.save_week_snapshot(day, {"institutions": {"1": {"rank": 3}}})
    assert await store.week_snapshot(day) == {"institutions": {"1": {"rank": 3}}}
    await store.save_week_snapshot(day, {"institutions": {}})
    assert await store.week_snapshot(day) == {"institutions": {}}


async def job_runs(env) -> None:
    store = env.store
    assert await store.job_last_run("digest") is None
    await store.set_job_run("digest", 1_700_000_000.5)
    assert await store.job_last_run("digest") == pytest.approx(1_700_000_000.5, abs=1e-3)
    await store.set_job_run("digest", 1_700_000_100.0)
    assert await store.job_last_run("digest") == pytest.approx(1_700_000_100.0, abs=1e-3)
    assert await store.job_last_run("spike") is None


async def status_rows_window(env) -> None:
    store = env.store
    now = datetime.now(UTC)
    rows = [
        (now - timedelta(days=5), {"cpu": 1}),
        (now - timedelta(hours=2), {"cpu": 2}),
        (now - timedelta(minutes=10), {"cpu": 3, "collection": {"telegram": {"lastOk": 1.5}}}),
    ]
    # Подкладываем не по порядку: ответ обязан идти по возрастанию времени.
    for observed_at, sample in (rows[2], rows[0], rows[1]):
        await env.seed_host_sample(observed_at, sample)
    got = await store.status_rows(3600)
    assert [row["sample"] for row in got] == [rows[2][1]]
    assert isinstance(got[0]["observed_at"], datetime)
    got = await store.status_rows(86400)
    assert [row["sample"] for row in got] == [rows[1][1], rows[2][1]]
    assert got[0]["observed_at"] < got[1]["observed_at"]
    got = await store.status_rows(10 * 86400)
    assert [row["sample"]["cpu"] for row in got] == [1, 2, 3]


CASES = [
    chat_alerts_rejected,
    recipients_roundtrip,
    announce_dedup_and_level_up,
    take_held_empties,
    migrate_chat_keeps_flags,
    prune_drops_old,
    mute_expiry,
    settings_roundtrip,
    week_snapshot_roundtrip,
    job_runs,
    status_rows_window,
]
