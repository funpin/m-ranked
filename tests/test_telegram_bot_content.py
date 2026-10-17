"""Дайджест и контентные уведомления: расписание, «выстрелил», «накрутка», снимки недели."""
from __future__ import annotations

import asyncio
import copy
from datetime import date, datetime
from zoneinfo import ZoneInfo

from test_telegram_bot_handlers import (
    GROUP,
    OUR_ID,
    PERSON,
    FakeSource as _HandlersSource,
    fixture,
    make_bot,
    sent_texts,
)

from telegram_bot import content
from telegram_bot.source import SourceUnavailable
from telegram_bot.store import OUR_INSTITUTION, Recipient

MSK = ZoneInfo("Europe/Moscow")
JOBS = ("spikes", "anomalies", "week_snapshot", "digest")


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """Октябрь 2026: 12-е — понедельник, 19-е — следующий понедельник."""
    return datetime(2026, 10, day, hour, minute, tzinfo=MSK)


def post(pid: str, *, index: float = 3.0, age: float = 10.0, promotion: bool = False,
         url: str = "https://example.org/p/1", views: int = 9200, level: int = 0) -> dict:
    return {"publicationId": pid, "institutionLegacyId": OUR_ID, "platform": "telegram",
            "publicationType": "photo", "publicUrl": url, "ageHours": age,
            "interactionIndex": index, "views": views, "promotion": promotion,
            "anomalyLevel": level}


def flagged(pid: str, level: int, url: str = "https://example.org/a/1") -> dict:
    return {"publicationId": pid, "institutionLegacyId": OUR_ID, "platform": "vk",
            "publicationType": "photo", "publicUrl": url, "views": 3400, "anomalyLevel": level}


class FakeSource(_HandlersSource):
    def __init__(self) -> None:
        super().__init__()
        self.spikes: list[dict] = []
        self.anomalies: list[dict] = []
        self.findings_args: list[dict] = []
        self.forecast_down = False

    async def findings(self, *, institution, platform, period, suspicious) -> dict:
        self._call("findings")
        self.findings_args.append(dict(institution=institution, platform=platform,
                                       period=period, suspicious=suspicious))
        if suspicious:
            return {"items": copy.deepcopy(self.spikes)}
        return fixture("findings_all.json" if institution is None else "findings_institution.json")

    async def anomalous(self, *, institution, period) -> dict:
        self._call("anomalous")
        return {"items": copy.deepcopy(self.anomalies)}

    async def forecast(self):
        if self.forecast_down:
            raise SourceUnavailable("forecast: ConnectError")
        return await super().forecast()


def make(**kwargs):
    bot, telegram, _, store = make_bot(**kwargs)
    source = FakeSource()
    bot.source = source
    return bot, telegram, source, store


def run(coro):
    return asyncio.run(coro)


def seeded(store, kind: str) -> None:
    """Пометить, что первый прогон уже был, чтобы дальше объявлять по-настоящему."""
    run(store.mark_announced(kind, "seed", 1))


def group_texts(telegram) -> list[str]:
    return sent_texts(telegram, GROUP)


# --- расписание ------------------------------------------------------------

def test_due_digest_monday_10():
    assert "digest" not in content.due(at(12, 9, 59), {})
    assert "digest" in content.due(at(12, 10), {})
    sent = at(12, 10, 1).timestamp()
    assert "digest" not in content.due(at(12, 10, 5), {"digest": sent})
    assert "digest" not in content.due(at(14, 12), {"digest": sent})
    # В понедельник не отправили: во вторник догоняем один раз.
    prior_week = at(5, 10, 2).timestamp()
    assert "digest" in content.due(at(13, 9), {"digest": prior_week})
    assert "digest" not in content.due(at(13, 9), {"digest": at(13, 8).timestamp()})
    # Следующая неделя снова ждёт понедельника 10:00.
    assert "digest" not in content.due(at(19, 9, 59), {"digest": sent})
    assert "digest" in content.due(at(19, 10), {"digest": sent})


def test_due_every_15_minutes():
    now = at(14, 12)
    stamp = now.timestamp()
    assert {"spikes", "anomalies"} <= set(content.due(now, {}))
    for last in (stamp - 60, stamp - 899):
        names = content.due(now, {"spikes": last, "anomalies": last})
        assert "spikes" not in names and "anomalies" not in names
    names = content.due(now, {"spikes": stamp - 900, "anomalies": stamp - 900})
    assert "spikes" in names and "anomalies" in names
    assert "alerts" in content.due(now, {"spikes": stamp, "anomalies": stamp})


def test_due_daily_jobs():
    now = at(14, 12)
    done = now.timestamp() - 60
    names = content.due(now, {"week_snapshot": done, "morning": done, "prune": done})
    assert not {"week_snapshot", "morning", "prune"} & set(names)
    names = content.due(at(14, 8, 59), {"morning": at(13, 8, 1).timestamp()})
    assert "morning" in names and "week_snapshot" not in names
    assert "week_snapshot" in content.due(at(14, 9), {"week_snapshot": at(13, 9, 5).timestamp()})
    assert "morning" not in content.due(at(14, 7, 59), {})
    assert "prune" in content.due(at(14, 0, 1), {"prune": at(13, 0, 1).timestamp()})


def test_due_uses_moscow_calendar_day():
    # 21:30 UTC = 00:30 MSK следующего дня: «сегодня» считается по московскому календарю.
    last = datetime(2026, 10, 13, 21, 30, tzinfo=ZoneInfo("UTC")).timestamp()
    assert "prune" not in content.due(at(14, 0, 20), {"prune": last})
    assert "prune" in content.due(at(15, 0, 20), {"prune": last})


# --- «выстрелил» -------------------------------------------------------------

def test_spike_thresholds():
    bot, telegram, source, store = make()
    seeded(store, "spike")
    source.spikes = [post("a", age=47.0, index=3.0), post("b", age=49.0), post("c", index=2.9), post("d", age=48.0)]
    assert run(content.check_spikes(bot)) == 1
    assert len(group_texts(telegram)) == 1
    assert source.findings_args[0] == dict(institution=OUR_ID, platform="all", period="7d",
                                           suspicious=True)
    assert run(content.check_spikes(bot)) == 0  # повторный прогон ничего не повторяет
    assert len(group_texts(telegram)) == 1
    assert run(store.job_last_run("spikes")) is not None


def test_spike_text():
    bot, telegram, source, store = make()
    seeded(store, "spike")
    source.spikes = [post("a", index=8.44, age=20.0, promotion=True, views=9200,
                          url="https://example.org/p?a=1&b=2")]
    run(content.check_spikes(bot))
    text = group_texts(telegram)[0]
    assert text.startswith("🚀 Наш пост выстрелил: ")
    assert '<a href="https://example.org/p?a=1&amp;b=2">ссылка</a>' in text
    assert "Telegram" in text and "×8,4" in text and "20 ч" in text and "9,2 тыс. просм." in text
    assert text.endswith("📣 продвижение")
    source.spikes = [post("b")]
    run(content.check_spikes(bot))
    assert "продвижение" not in group_texts(telegram)[-1]


def test_spike_missing_numbers_are_skipped():
    bot, telegram, source, store = make()
    seeded(store, "spike")
    source.spikes = [{**post("a"), "interactionIndex": None}, {**post("b"), "ageHours": None},
                     {**post("c"), "publicationId": None}]
    assert run(content.check_spikes(bot)) == 0
    assert group_texts(telegram) == []


def test_spike_goes_only_to_subscribers():
    bot, telegram, source, store = make()
    seeded(store, "spike")
    source.spikes = [post("a")]
    run(content.check_spikes(bot))
    assert len(group_texts(telegram)) == 1       # у чата spike=True
    assert sent_texts(telegram, PERSON) == []    # у человека только digest


def test_first_run_seeds_silently():
    bot, telegram, source, store = make()
    source.spikes = [post("a"), post("b", age=60.0)]
    source.anomalies = [flagged("x", 3), flagged("y", 1)]
    assert run(content.check_spikes(bot)) == 0
    assert run(content.check_anomalies(bot)) == 0
    assert telegram.of("send") == []
    assert run(store.has_announced_any("spike")) and run(store.has_announced_any("anomaly"))
    # Подходящее помечено: настоящий второй прогон их не повторяет, а новое объявляет.
    source.spikes.append(post("new"))
    assert run(content.check_spikes(bot)) == 1
    assert run(content.check_anomalies(bot)) == 0
    assert len(group_texts(telegram)) == 1


def test_empty_first_run_does_not_swallow_the_first_real_post():
    bot, telegram, source, store = make()
    assert run(content.check_spikes(bot)) == 0   # прогон без подходящих постов
    source.spikes = [post("a")]
    assert run(content.check_spikes(bot)) == 1   # он не должен сойти за «первый прогон»
    assert len(group_texts(telegram)) == 1


# --- «накрутка» --------------------------------------------------------------

def test_anomaly_levels():
    bot, telegram, source, store = make()
    seeded(store, "anomaly")
    source.anomalies = [flagged("a", 2), flagged("b", 1)]
    assert run(content.check_anomalies(bot)) == 1
    assert source.calls.count("anomalous") == 1
    first = group_texts(telegram)[0]
    assert first.startswith("⚠️ Вероятно, накрутка на нашем посте: ")
    assert "ВКонтакте" in first and "3,4 тыс. просм." in first
    assert '<a href="https://example.org/a/1">ссылка</a>' in first
    source.anomalies = [flagged("a", 3), flagged("b", 1)]
    assert run(content.check_anomalies(bot)) == 1
    second = group_texts(telegram)[1]
    assert second.startswith("⚠️ Накрутка на нашем посте: ")
    assert run(content.check_anomalies(bot)) == 0   # дальше без повторов
    assert len(group_texts(telegram)) == 2
    source.anomalies = [flagged("a", 2)]            # спад уровня не объявляется заново
    assert run(content.check_anomalies(bot)) == 0


def test_anomaly_goes_only_to_anomaly_subscribers():
    bot, telegram, source, store = make(recipients=[
        Recipient(PERSON, "person", "человек", spike=True),
        Recipient(GROUP, "chat", "чат", anomaly=True)])
    seeded(store, "anomaly")
    source.anomalies = [flagged("a", 3)]
    run(content.check_anomalies(bot))
    assert len(group_texts(telegram)) == 1 and sent_texts(telegram, PERSON) == []


# --- недоступность и «вуз не выбран» -----------------------------------------

def test_jobs_do_nothing_without_our_institution():
    bot, telegram, source, store = make(our=None)
    seeded(store, "spike")
    seeded(store, "anomaly")
    source.spikes, source.anomalies = [post("a")], [flagged("a", 3)]
    assert run(content.check_spikes(bot)) == 0
    assert run(content.check_anomalies(bot)) == 0
    assert run(content.record_week(bot)) is None
    assert run(content.send_digest(bot)) is None
    assert telegram.of("send") == [] and source.calls == []
    for job in JOBS:
        assert run(store.job_last_run(job)) is None
    assert run(store.week_snapshot(date(2026, 10, 16))) is None


def test_source_down_is_not_marked_as_run():
    bot, telegram, source, store = make()
    source.down = True
    assert run(content.check_spikes(bot)) == 0
    assert run(content.check_anomalies(bot)) == 0
    assert run(content.record_week(bot)) is None
    assert run(content.send_digest(bot)) is None
    assert telegram.of("send") == []
    for job in JOBS:
        assert run(store.job_last_run(job)) is None
    assert not run(store.has_announced_any("spike"))
    source.down = False  # после восстановления тот же прогон отрабатывает
    source.spikes = [post("a")]
    run(content.check_spikes(bot))
    assert run(store.job_last_run("spikes")) is not None


# --- неделя к неделе -----------------------------------------------------------

def test_record_week_saves_our_stats():
    bot, _, source, store = make()
    run(content.record_week(bot))
    # NOW бота — 2026-10-16 15:00 UTC = 18:00 MSK.
    saved = run(store.week_snapshot(date(2026, 10, 16)))
    assert saved == {"telegram": {"posts": 20, "views": 112000, "reactions": 3400},
                     "vk": {"posts": 8, "views": 15000, "reactions": 900}}
    assert run(store.job_last_run("week_snapshot")) == bot.clock()


def test_record_week_key_is_moscow_date():
    bot, _, _, store = make()
    bot.clock = lambda: datetime(2026, 10, 16, 21, 30, tzinfo=ZoneInfo("UTC")).timestamp()
    run(content.record_week(bot))  # 00:30 MSK уже 17-го
    assert run(store.week_snapshot(date(2026, 10, 17))) is not None
    assert run(store.week_snapshot(date(2026, 10, 16))) is None


def test_record_week_skips_empty_stats():
    bot, _, source, store = make()
    original = source.dashboard

    async def empty() -> dict:
        body = await original()
        return {**body, "stats": []}

    source.dashboard = empty
    run(content.record_week(bot))
    assert run(store.week_snapshot(date(2026, 10, 16))) is None


# --- дайджест ------------------------------------------------------------------

def test_digest_contents():
    bot, telegram, source, store = make()
    run(store.save_week_snapshot(date(2026, 10, 9), {"telegram": {"posts": 10, "views": 56000,
                                                                  "reactions": 3400}}))
    run(content.send_digest(bot))
    texts = group_texts(telegram)
    text = "\n".join(texts)
    assert texts[0].startswith("<b>Дайджест")
    assert "Наши лучшие посты" in text and "Лучшие у других вузов" in text
    assert "Неделя к неделе" in text
    assert "постов 20 (+100 %)" in text            # неделя к неделе по сохранённому снимку
    assert "Прогноз места в М-Рейтинге" in text and "±" in text
    others = text.split("Лучшие у других вузов")[1].split("Неделя к неделе")[0]
    assert "(мы)" not in others and "Дельта" not in others   # наш вуз среди «других» не показываем
    assert sent_texts(telegram, PERSON) == texts            # получатели с digest
    assert len(texts) >= 1
    assert run(store.job_last_run("digest")) == bot.clock()
    # Дайджест читает без аномалий: подозрительные посты в «лучшие» не попадают.
    assert all(call["suspicious"] is False for call in source.findings_args)
    assert {call["institution"] for call in source.findings_args} == {OUR_ID, None}


def test_digest_without_forecast_and_previous():
    bot, telegram, source, _ = make()
    source.forecast_down = True
    run(content.send_digest(bot))
    text = "\n".join(group_texts(telegram))
    assert "Прогноз места" not in text and "Первая неделя наблюдений" in text


def test_digest_goes_only_to_digest_subscribers():
    bot, telegram, _, _ = make(recipients=[Recipient(PERSON, "person", "человек"),
                                           Recipient(GROUP, "chat", "чат", digest=True)])
    run(content.send_digest(bot))
    assert group_texts(telegram) and sent_texts(telegram, PERSON) == []


def test_send_digest_here_matches_scheduled_digest():
    bot, telegram, _, _ = make()
    run(content.send_digest(bot))
    scheduled = group_texts(telegram)
    telegram.calls.clear()
    run(bot.send_digest_here(GROUP))
    assert group_texts(telegram) == scheduled and sent_texts(telegram, PERSON) == []


def test_send_digest_here_without_our_institution():
    bot, telegram, _, _ = make(our=None)
    run(bot.send_digest_here(GROUP))
    assert group_texts(telegram) == ["админ ещё не выбрал наш вуз: /settings"]
