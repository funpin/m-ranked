"""Серверы в боте: кнопки под /status, состояние сервера, кэш, кулдаун и
живые сеансы с лимитами."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from telegram_bot import servers as servers_module
from telegram_bot.servers import LocalHost, ServerMonitor, bar, parse_data, server_buttons, sparkline
from telegram_bot.store import MemoryStore
from tests.test_telegram_bot_handlers import ADMIN, PERSON, callback, handle, make_bot, private_message

UTC = timezone.utc


def write_proc(root: Path, busy: int = 50, idle: int = 50) -> None:
    (root / "self" / "net").mkdir(parents=True, exist_ok=True)
    (root / "stat").write_text(f"cpu  {busy} 0 0 {idle} 0 0 0 0\n")
    (root / "meminfo").write_text("MemTotal: 4000000 kB\nMemAvailable: 1000000 kB\n")
    (root / "loadavg").write_text("1.42 1.31 1.28 1/1 1\n")
    (root / "self" / "net" / "dev").write_text("h\nh\n  eth0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n")
    (root / "diskstats").write_text("")


def seed(store: MemoryStore) -> None:
    now = datetime.now(UTC)
    report = {"processes": {"release": "v2026.11.0", "tasks": [
        {"unit": "collector@telegram", "active": "active", "since": 1.0},
        {"unit": "dump-backup", "scheduled": True, "active": "activating", "startedAt": now.timestamp() - 420}],
        "collectors": {"telegram": {"lastSuccessAt": now.timestamp() - 60, "cycleSeconds": 61, "scheduleLagSeconds": 2}},
        "transfer": {"backlog": 3}},
        "metrics": {"cpus": 1, "memoryTotalBytes": 2 * 10**9, "memoryAvailableBytes": 10**9,
                    "diskTotalBytes": 30 * 10**9, "diskFreeBytes": 14 * 10**9, "load1": 1.8}}
    store.nodes = [
        {"id": "server-2", "display_name": "Сервер 2 · основной", "role": "main", "state": "active", "platforms": [],
         "last_seen_at": now, "report": {"processes": {"release": "v2026.11.0", "tasks": [
             {"unit": "api", "active": "active", "since": 1.0}]}}},
        {"id": "server-1", "display_name": "Сервер 1 · сбор", "role": "collector", "state": "active",
         "platforms": ["telegram"], "last_seen_at": now, "report": report}]
    store.host_samples = [{"observed_at": now - timedelta(seconds=60 * (30 - index)),
                           "sample": {"cpu": {"total": index * 1000, "idle": index * 600}, "rel": "v2026.11.0",
                                      "disk": {"total": 50 * 10**9, "free": 22 * 10**9}, "cores": 2}}
                          for index in range(1, 30)] + [
        {"observed_at": now - timedelta(minutes=minute), "sample": {"rel": "v2026.11.0"}} for minute in range(1450, 30, -1)]
    store.host_samples.sort(key=lambda row: row["observed_at"])
    # Пропуск у сборщика: точек не было с 70-й по 61-ю минуту назад.
    store.node_points["server-1"] = [
        {"observed_at": now - timedelta(minutes=minute), "cpu_percent": 70.0, "memory_total_bytes": 2 * 10**9,
         "memory_available_bytes": 10**9, "release": "v2026.11.0"} for minute in range(1450, 0, -1)
        if not 61 < minute < 70]
    store.run_starts = [{"platform": "telegram", "started": now.timestamp() - minute * 60} for minute in range(0, 1440, 5)]


class CountingStore(MemoryStore):
    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    async def node_samples(self, node, seconds):
        self.reads += 1
        return await super().node_samples(node, seconds)


async def no_sleep(_: float) -> None:
    return None


def make_monitor(tmp_path: Path, store: MemoryStore | None = None) -> ServerMonitor:
    store = store or MemoryStore()
    seed(store)
    write_proc(tmp_path)
    return ServerMonitor(store, local=LocalHost(proc=tmp_path, sleep=no_sleep))


def test_bars_and_sparklines() -> None:
    assert bar(0) == "▱" * 10 and bar(100) == "▰" * 10 and bar(46) == "▰" * 5 + "▱" * 5
    assert bar(None) == "·" * 10 and bar(250) == "▰" * 10
    assert sparkline([0, 50, 100, None]) == "▁▄█ "


@pytest.mark.parametrize("data", ["st|s|Server-1", "st|s|", "st|q|server-1", "st|s|server-1|x",
                                  "st|s|a;rm -rf", "st|s|" + "a" * 41, "t|s|server-1"])
def test_foreign_and_broken_buttons_are_rejected(data: str) -> None:
    assert parse_data(data) is None


def test_server_buttons_one_per_server(tmp_path: Path) -> None:
    monitor = make_monitor(tmp_path)
    keyboard = server_buttons(asyncio.run(monitor.servers()))
    assert [row[0]["callback_data"] for row in keyboard] == ["st|s|server-2", "st|s|server-1"]
    assert keyboard[0][0]["text"].startswith("🟢 Сервер 2")


def test_collector_view_has_load_processes_and_gaps(tmp_path: Path) -> None:
    message = asyncio.run(make_monitor(tmp_path).message("server-1"))
    assert message is not None
    text = message.text
    assert "Сервер 1 · сбор" in text and "<code>v2026.11.0</code>" in text
    assert "CPU  ▰▰▰▰▰▰▰▱▱▱  70%" in text
    assert "цикл 61 с" in text and "в очереди 3" in text and "идёт dump-backup · 7 мин" in text
    assert "🟡 Точки агента: 1, всего 9 мин" in text and "🟢 Сбор: пропусков нет" in text
    assert [button["callback_data"] for button in message.keyboard[0]] == ["st|r", "st|s|server-1", "st|v|server-1"]


def test_main_view_reads_local_proc_without_background_polling(tmp_path: Path) -> None:
    monitor = make_monitor(tmp_path)
    message = asyncio.run(monitor.message("server-2"))
    assert message is not None
    assert "RAM  ▰▰▰▰▰▰▰▰▱▱  75%" in message.text  # 3 из 4 ГБ заняты по meminfo бота
    assert "Приём с сборщиков" in message.text and "🟢 Снимки сервера: пропусков нет" in message.text
    assert asyncio.run(monitor.message("missing")) is None


def test_views_are_cached_across_chats(tmp_path: Path) -> None:
    store = CountingStore()
    monitor = make_monitor(tmp_path, store)
    for _ in range(5):
        asyncio.run(monitor.message("server-1"))
    assert store.reads == 1


def test_press_cooldown_per_chat() -> None:
    clock = [100.0]
    monitor = ServerMonitor(MemoryStore(), monotonic=lambda: clock[0])
    assert not monitor.pressed_too_often(1)
    assert monitor.pressed_too_often(1) and not monitor.pressed_too_often(2)
    clock[0] += 3.1
    assert not monitor.pressed_too_often(1)


def test_live_sessions_are_limited_and_end_with_a_still_message(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(servers_module.LIVE_STEP_SECONDS, "node", 0.01)
    monkeypatch.setattr(servers_module, "LIVE_SECONDS", 0.035)
    monitor = make_monitor(tmp_path)
    edits: list = []

    async def run() -> None:
        async def edit(message) -> None:
            edits.append(message)

        assert all(monitor.start_live(chat, 10, "server-1", "node", edit) for chat in (1, 2, 3))
        assert not monitor.start_live(4, 10, "server-1", "node", edit)   # больше трёх — нельзя
        assert monitor.start_live(1, 11, "server-1", "node", edit)       # тот же чат — замена
        await asyncio.sleep(0.2)

    asyncio.run(run())
    assert monitor.live == {}
    assert edits and "▶ Вживую 2 мин" in [button["text"] for button in edits[-1].keyboard[0]]
    assert any("вживую до" in message.text for message in edits)


def test_bot_status_lists_servers_and_opens_one(tmp_path: Path) -> None:
    bot, telegram, _, store = make_bot()
    seed(store)
    write_proc(tmp_path)
    bot.servers.local = LocalHost(proc=tmp_path, sleep=no_sleep)
    handle(bot, private_message(ADMIN, "/status"))
    sent = telegram.of("send")[-1]
    assert [row[0]["callback_data"] for row in sent[3]] == ["st|s|server-2", "st|s|server-1", "st|r"]
    assert "Пропуски снимков за 3 ч" in sent[2]
    handle(bot, callback(ADMIN, ADMIN, sent[4], "st|s|server-1"))
    assert "Сервер 1 · сбор" in telegram.of("edit")[-1][3]
    # Повторное нажатие сразу — кулдаун, без чтения и без правки.
    handle(bot, callback(ADMIN, ADMIN, sent[4], "st|s|server-1"))
    assert telegram.of("answer")[-1][2].startswith("не так часто")
    assert len(telegram.of("edit")) == 1


def test_server_buttons_refused_to_people_without_alerts() -> None:
    bot, telegram, _, store = make_bot()
    seed(store)
    handle(bot, callback(PERSON, PERSON, 5, "st|s|server-1"))
    handle(bot, callback(ADMIN, ADMIN, 5, "st|s|unknown-server"))
    assert telegram.of("edit") == []
    assert [call[2] for call in telegram.of("answer")] == ["недоступно", "кнопка устарела"]
