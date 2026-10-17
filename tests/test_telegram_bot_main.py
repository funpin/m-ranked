"""Основной цикл бота: опрос Telegram и минутный тик задач."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from telegram_bot import __main__ as entry
from telegram_bot import alerts_inbox, content
from telegram_bot.config import BotConfig
from telegram_bot.content import due
from telegram_bot.handlers import Bot
from telegram_bot.store import MemoryStore

MSK = ZoneInfo("Europe/Moscow")
NOON = datetime(2026, 10, 16, 12, 0, tzinfo=MSK)
ADMIN = 7


class FakeTelegram:
    """get_updates отдаёт заготовленные пачки, потом висит, как длинный опрос."""

    def __init__(self, batches: list[list[dict]] | None = None) -> None:
        self.batches = list(batches or [])
        self.offsets: list[int | None] = []
        self.calls: list[tuple] = []

    async def get_me(self) -> dict:
        return {"username": "test_bot"}

    async def set_commands(self, commands, scope) -> None:
        self.calls.append(("set_commands", scope))

    async def get_updates(self, offset, timeout=50) -> list[dict]:
        self.offsets.append(offset)
        if self.batches:
            return self.batches.pop(0)
        await asyncio.sleep(3600)
        return []


def make_bot(tmp_path: Path, telegram: FakeTelegram | None = None, now: datetime = NOON):
    config = BotConfig(token="test-token", admin_ids=frozenset({ADMIN}),
                       api_base_url="http://api.test", dsn="postgresql://test",
                       spool_dir=tmp_path)
    store = MemoryStore()
    bot = Bot(telegram or FakeTelegram(), None, store, config,  # type: ignore[arg-type]
              clock=lambda: now.timestamp())
    return bot, store


@pytest.fixture
def jobs(monkeypatch):
    """Подменяет все задачи записывающими заглушками; имя → число запусков."""
    ran: dict[str, int] = {}

    def stub(label: str):
        async def job(bot, *args):
            ran[label] = ran.get(label, 0) + 1
        return job

    monkeypatch.setattr(content, "check_spikes", stub("spikes"))
    monkeypatch.setattr(content, "check_anomalies", stub("anomalies"))
    monkeypatch.setattr(content, "record_week", stub("week_snapshot"))
    monkeypatch.setattr(content, "send_digest", stub("digest"))
    monkeypatch.setattr(alerts_inbox, "deliver", stub("alerts"))
    monkeypatch.setattr(alerts_inbox, "morning", stub("morning"))
    return ran


def test_tick_runs_every_due_job(tmp_path, jobs):
    bot, store = make_bot(tmp_path)
    asyncio.run(entry.tick(bot))
    # prune идёт без заглушки: это метод хранилища.
    assert set(jobs) | {"prune"} == set(due(NOON, {}))


def test_tick_marks_only_its_own_jobs(tmp_path, jobs):
    bot, store = make_bot(tmp_path)
    asyncio.run(entry.tick(bot))
    # Задачи spikes/anomalies/week_snapshot/digest отмечают себя сами (здесь — заглушки).
    assert asyncio.run(store.job_last_run("morning")) == NOON.timestamp()
    assert asyncio.run(store.job_last_run("prune")) == NOON.timestamp()
    for name in ("spikes", "anomalies", "week_snapshot", "digest"):
        assert asyncio.run(store.job_last_run(name)) is None


def test_second_tick_does_not_repeat_daily_jobs(tmp_path, jobs):
    bot, _ = make_bot(tmp_path)
    asyncio.run(entry.tick(bot))
    jobs.clear()
    asyncio.run(entry.tick(bot))
    assert "morning" not in jobs and "prune" not in jobs
    assert jobs.get("alerts") == 1  # очередь тревог разбирается на каждом тике


def test_job_error_does_not_stop_loop(tmp_path, jobs, monkeypatch, caplog):
    async def broken(bot):
        raise RuntimeError("секрет-в-тексте-ошибки")

    monkeypatch.setattr(content, "check_spikes", broken)
    bot, store = make_bot(tmp_path)
    with caplog.at_level(logging.INFO):
        asyncio.run(entry.tick(bot))
        asyncio.run(entry.tick(bot))
    # Остальные задачи после упавшей выполнены, следующий тик тоже состоялся.
    assert jobs["anomalies"] == 2 and jobs["alerts"] == 2
    assert "RuntimeError" in caplog.text
    assert "секрет-в-тексте-ошибки" not in caplog.text
    # Упавшая задача не отмечена как выполненная — её не пропустят.
    assert asyncio.run(store.job_last_run("morning")) == NOON.timestamp()


def test_failed_morning_is_not_marked(tmp_path, jobs, monkeypatch):
    async def broken(bot, now):
        raise ConnectionError

    monkeypatch.setattr(alerts_inbox, "morning", broken)
    bot, store = make_bot(tmp_path)
    asyncio.run(entry.tick(bot))
    assert asyncio.run(store.job_last_run("morning")) is None
    assert asyncio.run(store.job_last_run("prune")) == NOON.timestamp()


def test_store_failure_in_tick_is_logged_not_raised(tmp_path, jobs, caplog):
    bot, store = make_bot(tmp_path)

    async def down(name):
        raise OSError("секрет")

    store.job_last_run = down  # type: ignore[method-assign]
    with caplog.at_level(logging.INFO):
        asyncio.run(entry.tick(bot))
    assert "OSError" in caplog.text and "секрет" not in caplog.text
    assert jobs == {}


def test_tick_passes_moscow_aware_now(tmp_path, monkeypatch):
    seen: list[datetime] = []

    async def deliver(bot, now):
        seen.append(now)

    monkeypatch.setattr(alerts_inbox, "deliver", deliver)
    monkeypatch.setattr(content, "check_spikes", lambda bot: asyncio.sleep(0))
    monkeypatch.setattr(content, "check_anomalies", lambda bot: asyncio.sleep(0))
    bot, _ = make_bot(tmp_path)
    asyncio.run(entry.tick(bot))
    assert seen and seen[0].tzinfo is not None and seen[0].utcoffset().total_seconds() == 3 * 3600


def run_for(bot, config, seconds: float, **kwargs) -> None:
    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(entry.run(config, stop=stop, bot=bot, **kwargs))
        await asyncio.sleep(seconds)
        stop.set()
        await asyncio.wait_for(task, 2)

    asyncio.run(scenario())


def test_stop_event_exits(tmp_path, jobs):
    bot, _ = make_bot(tmp_path)  # get_updates висит на час: стоп не должен его ждать
    run_for(bot, bot.config, 0.05)


def test_stop_during_long_poll_is_not_an_error(tmp_path, jobs, caplog):
    # Прерванный стопом длинный опрос — штатная остановка, а не сбой getUpdates
    # (было: InvalidStateError в журнале при каждом перезапуске службы).
    bot, _ = make_bot(tmp_path)
    with caplog.at_level(logging.ERROR, logger="telegram_bot"):
        run_for(bot, bot.config, 0.05)
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


def test_run_sets_up_and_installs_mute_hook(tmp_path, jobs):
    bot, store = make_bot(tmp_path)
    original = bot.on_mute_callback
    run_for(bot, bot.config, 0.05)
    assert bot.on_mute_callback != original
    assert bot.username == "test_bot"
    assert asyncio.run(store.recipients())  # setup() записал админа


def test_updates_are_handled_and_offset_advances(tmp_path, jobs):
    handled: list[int] = []
    telegram = FakeTelegram([[{"update_id": 10, "message": {}}, {"update_id": 11}], []])
    bot, _ = make_bot(tmp_path, telegram)

    async def handle(update):
        handled.append(update["update_id"])

    bot.handle = handle  # type: ignore[method-assign]
    run_for(bot, bot.config, 0.1)
    assert handled == [10, 11]
    assert telegram.offsets[:3] == [None, 12, 12]


def test_poison_update_is_skipped_and_logged_by_class_only(tmp_path, jobs, caplog):
    handled: list[int] = []
    telegram = FakeTelegram([[{"update_id": 5}, {"update_id": 6}]])
    bot, _ = make_bot(tmp_path, telegram)

    async def handle(update):
        if update["update_id"] == 5:
            raise ValueError("текст с секретом")
        handled.append(update["update_id"])

    bot.handle = handle  # type: ignore[method-assign]
    with caplog.at_level(logging.INFO):
        run_for(bot, bot.config, 0.1)
    assert handled == [6]  # упавшее не остановило пачку
    assert telegram.offsets[1] == 7  # и не будет присылаться снова
    assert "ValueError" in caplog.text and "секретом" not in caplog.text


def test_polling_error_is_logged_and_retried(tmp_path, jobs, monkeypatch, caplog):
    monkeypatch.setattr(entry, "POLL_ERROR_PAUSE_SECONDS", 0.01)
    telegram = FakeTelegram()
    calls = {"n": 0}

    async def flaky(offset, timeout=50):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("секрет")
        await asyncio.sleep(3600)

    telegram.get_updates = flaky  # type: ignore[method-assign]
    bot, _ = make_bot(tmp_path, telegram)
    with caplog.at_level(logging.INFO):
        run_for(bot, bot.config, 0.2)
    assert calls["n"] >= 3
    assert "RuntimeError" in caplog.text and "секрет" not in caplog.text


def test_ticks_repeat_while_running(tmp_path, jobs):
    bot, _ = make_bot(tmp_path)
    run_for(bot, bot.config, 0.2, tick_seconds=0.02)
    assert jobs["alerts"] >= 3


def test_main_reports_bad_config_without_traceback(monkeypatch, caplog):
    for name in ("TELEGRAM_BOT_TOKEN_FILE", "TELEGRAM_BOT_ADMIN_IDS", "TELEGRAM_BOT_DSN"):
        monkeypatch.delenv(name, raising=False)
    with caplog.at_level(logging.ERROR):
        assert entry.main() == 2
    assert "TELEGRAM_BOT_TOKEN_FILE" in caplog.text


def test_main_keeps_httpx_quiet(monkeypatch):
    # Адрес запроса к Telegram содержит токен: httpx на INFO его бы напечатал.
    logging.getLogger("httpx").setLevel(logging.INFO)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_FILE", raising=False)
    entry.main()
    assert logging.getLogger("httpx").level == logging.WARNING
