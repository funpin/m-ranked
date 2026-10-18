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

from telegram_bot import content, emoji
from telegram_bot.emoji import icon
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
        self.top_queries: list = []
        self.forecast_down = False

    async def findings(self, *, institution, platform, period, suspicious) -> dict:
        self._call("findings")
        self.findings_args.append(dict(institution=institution, platform=platform,
                                       period=period, suspicious=suspicious))
        if suspicious:
            return {"items": copy.deepcopy(self.spikes)}
        return fixture("findings_all.json" if institution is None else "findings_institution.json")

    async def top_body(self, query, our_id) -> dict:
        # Как ApiSource.top_body для «наших»: один запрос «Находок» (догрузку
        # площадок проверяет test_digest_ours_uses_top_body_with_platform_top_up).
        self.top_queries.append(query)
        return await self.findings(institution=our_id, platform=query.platform,
                                   period=query.period, suspicious=query.suspicious)

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


def test_due_digest_fresh_install_waits_for_monday():
    assert "digest" not in content.due(at(14, 12), {})            # среда, дайджестов ещё не было
    assert "digest" not in content.due(at(12, 9, 59), {})
    assert "digest" in content.due(at(12, 10), {})                # понедельник 10:00
    previous_week = at(8, 10, 1).timestamp()                      # прошлая неделя, дайджест был
    assert "digest" in content.due(at(13, 9), {"digest": previous_week})   # вторник — догоняем
    assert "digest" not in content.due(at(13, 9), {"digest": at(13, 9, 1).timestamp()})


def test_due_requires_aware_now():
    import pytest
    with pytest.raises(ValueError):
        content.due(datetime(2026, 10, 12, 10, 0), {})


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


def test_spike_skips_flagged_posts():
    bot, telegram, source, store = make()
    seeded(store, "spike")
    source.spikes = [post("a", index=4.0, age=10.0, level=2), post("b", level=3),
                     post("c", level=1)]
    assert run(content.check_spikes(bot)) == 1          # только уровень 1 («спорный») проходит
    assert len(group_texts(telegram)) == 1
    assert run(store.mark_announced("spike", "a", 1))   # «a» не помечен как объявленный
    assert run(store.mark_announced("spike", "b", 1))


def test_spike_text():
    bot, telegram, source, store = make()
    seeded(store, "spike")
    source.spikes = [post("a", index=8.44, age=20.0, promotion=True, views=9200,
                          url="https://example.org/p?a=1&b=2")]
    run(content.check_spikes(bot))
    text = group_texts(telegram)[0]
    assert text.startswith(icon("spike") + " Наш пост выстрелил: ")
    assert '<a href="https://example.org/p?a=1&amp;b=2">ссылка</a>' in text
    assert "Telegram" in text and "×8,4" in text and "20 ч" in text and "9,2 тыс. просм." in text
    assert text.endswith(icon("promo") + " продвижение")
    source.spikes = [post("b")]
    run(content.check_spikes(bot))
    assert "продвижение" not in group_texts(telegram)[-1]


def test_notification_icons_come_from_slots(monkeypatch):
    item = post("a", promotion=True)
    assert content.spike_message(item).text.startswith("🚀 ")
    assert content.anomaly_message(flagged("x", 3), 3).text.startswith("⚠️ ")
    # Когда у слотов появятся id набора, значки станут кастомными без правок текстов.
    fake = "1234567890123456789"
    for slot in ("spike", "anomaly", "promo"):
        monkeypatch.setitem(emoji.SLOTS, slot, (emoji.SLOTS[slot][0], fake))
    spike = content.spike_message(item).text
    assert spike.startswith(f'<tg-emoji emoji-id="{fake}">🚀</tg-emoji> Наш пост выстрелил: ')
    assert spike.endswith(f'<tg-emoji emoji-id="{fake}">📣</tg-emoji> продвижение')
    assert content.anomaly_message(flagged("x", 3), 3).text.startswith(
        f'<tg-emoji emoji-id="{fake}">⚠️</tg-emoji> Накрутка на нашем посте: ')


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
    assert first.startswith(icon("anomaly") + " Вероятно, накрутка на нашем посте: ")
    assert "ВКонтакте" in first and "3,4 тыс. просм." in first
    assert '<a href="https://example.org/a/1">ссылка</a>' in first
    source.anomalies = [flagged("a", 3), flagged("b", 1)]
    assert run(content.check_anomalies(bot)) == 1
    second = group_texts(telegram)[1]
    assert second.startswith(icon("anomaly") + " Накрутка на нашем посте: ")
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
    assert texts[0].startswith("🏆 <b>НАШИ ЛУЧШИЕ</b>")   # шапка — в подписи к обложке
    assert "<b>НАШИ ЛУЧШИЕ</b>" in text and "<b>ДРУГИЕ ВУЗЫ</b>" in text
    assert "<b>НЕДЕЛЯ</b>" in text and "<b>ПРОГНОЗ</b>" in text
    assert "20 постов (+100 %)" in text            # неделя к неделе по сохранённому снимку
    assert "Прогноз места в М-Рейтинге" in text and "±" in text
    others = text.split("<b>ДРУГИЕ ВУЗЫ</b>")[1].split("<b>НЕДЕЛЯ</b>")[0]
    assert "(мы)" not in others and "Дельта" not in others   # наш вуз среди «других» не показываем
    assert sent_texts(telegram, PERSON) == texts            # получатели с digest
    assert len(texts) >= 1
    assert run(store.job_last_run("digest")) == bot.clock()
    # Дайджест читает без аномалий: подозрительные посты в «лучшие» не попадают.
    assert all(call["suspicious"] is False for call in source.findings_args)
    assert {call["institution"] for call in source.findings_args} == {OUR_ID, None}
    from telegram_bot.words import TopQuery
    assert source.top_queries == [TopQuery()]   # наши лучшие — как /top по умолчанию


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
    photos = telegram.of("photo")
    assert [call[1] for call in photos] == [GROUP]
    assert photos[0][2].startswith(b"\x89PNG")       # один чат — своя загрузка
    assert photos[0][3] == "<b>Дайджест · Дельта · 10–16 окт</b>"


def test_send_digest_here_without_our_institution():
    bot, telegram, _, _ = make(our=None)
    run(bot.send_digest_here(GROUP))
    assert group_texts(telegram) == ["админ ещё не выбрал наш вуз: /settings"]


# --- смена «нашего вуза» -------------------------------------------------------

def test_changed_institution_seeds_silently_then_announces_new_posts():
    bot, telegram, source, store = make()
    seeded(store, "spike")
    seeded(store, "anomaly")
    source.spikes, source.anomalies = [post("a")], [flagged("x", 3)]
    assert run(content.check_spikes(bot)) == 1
    assert run(content.check_anomalies(bot)) == 1
    # Админ сменил наш вуз: свежие посты нового вуза — история, а не новость.
    run(store.set_setting(OUR_INSTITUTION, 12, 7))
    source.spikes = [post("b"), post("c")]
    source.anomalies = [flagged("y", 2), flagged("z", 3)]
    assert run(content.check_spikes(bot)) == 0
    assert run(content.check_anomalies(bot)) == 0
    assert len(group_texts(telegram)) == 2
    assert source.findings_args[-1]["institution"] == 12
    # Следующий прогон объявляет только новое.
    source.spikes.append(post("d"))
    source.anomalies.append(flagged("w", 2))
    assert run(content.check_spikes(bot)) == 1
    assert run(content.check_anomalies(bot)) == 1
    assert len(group_texts(telegram)) == 4


def test_same_institution_does_not_seed_again():
    bot, telegram, source, store = make()
    assert run(content.check_spikes(bot)) == 0       # первый прогон на установке — пустой
    run(store.set_setting(OUR_INSTITUTION, OUR_ID, 7))  # админ выбрал тот же вуз
    source.spikes = [post("a")]
    assert run(content.check_spikes(bot)) == 1
    assert len(group_texts(telegram)) == 1


def test_source_down_after_institution_change_keeps_seeding_pending():
    bot, telegram, source, store = make()
    seeded(store, "spike")
    run(content.check_spikes(bot))
    run(store.set_setting(OUR_INSTITUTION, 12, 7))
    source.down = True
    assert run(content.check_spikes(bot)) == 0
    source.down = False
    source.spikes = [post("b")]
    assert run(content.check_spikes(bot)) == 0       # засев не потерялся из-за сбоя API
    assert group_texts(telegram) == []


# --- дайджест: наши посты как в /top ------------------------------------------

def test_digest_ours_uses_top_body_with_platform_top_up():
    import httpx

    from telegram_bot.source import ApiSource, make_client

    base = fixture("findings_institution.json")
    base["hasMore"] = True
    base["items"] = [i for i in base["items"] if i["platform"] != "vk"]  # ВК не попал на страницу
    vk_body = fixture("findings_institution.json")
    vk_body["items"] = [i for i in vk_body["items"] if i["platform"] == "vk"]
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen.append({"path": request.url.path, **params})
        if request.url.path == "/api/v1/compare/dashboard":
            return httpx.Response(200, json=fixture("dashboard.json"))
        if request.url.path == "/api/v1/rating/forecast":
            return httpx.Response(200, json=fixture("forecast.json"))
        if params.get("mode") == "all":
            return httpx.Response(200, json=fixture("findings_all.json"))
        return httpx.Response(200, json=vk_body if params.get("platform") == "vk" else base)

    bot, telegram, _, _ = make()
    bot.source = ApiSource(make_client("http://api.test", transport=httpx.MockTransport(handler)))
    messages = run(content.build_digest(bot))
    ours = "\n".join(m.text for m in messages).split("<b>ДРУГИЕ ВУЗЫ</b>")[0]
    assert f'{icon("vk")} {icon("rank_1")} <a href="https://example.org/vk/19">' in ours
    ours_requests = [r for r in seen if r.get("mode") == "institution"]
    assert [r["platform"] for r in ours_requests][0] == "all"
    assert "vk" in [r["platform"] for r in ours_requests]
    assert all(r["anomalies"] == "exclude" and r["period"] == "7d" for r in ours_requests)


# --- дайджест: недоставленный не отмечается -----------------------------------

def test_digest_not_marked_when_telegram_failed_for_everyone():
    bot, telegram, _, store = make()
    telegram.failing = {PERSON, GROUP}
    run(content.send_digest(bot))
    assert run(store.job_last_run("digest")) is None   # следующий тик повторит
    telegram.failing = set()
    run(content.send_digest(bot))
    assert group_texts(telegram) and run(store.job_last_run("digest")) == bot.clock()


def test_digest_marked_when_delivered_to_someone():
    bot, telegram, _, store = make()
    telegram.failing = {PERSON}
    run(content.send_digest(bot))
    assert group_texts(telegram) and run(store.job_last_run("digest")) == bot.clock()


def test_digest_marked_without_digest_recipients():
    bot, telegram, _, store = make(recipients=[Recipient(PERSON, "person", "человек")])
    run(content.send_digest(bot))
    assert telegram.of("send") == [] and run(store.job_last_run("digest")) == bot.clock()


def test_digest_marked_when_nobody_can_receive_it_anyway():
    # Человек ещё не нажал /start: повтор каждую минуту ему не поможет.
    bot, telegram, _, store = make(recipients=[Recipient(PERSON, "person", "человек", digest=True)])
    telegram.not_started = {PERSON}
    run(content.send_digest(bot))
    assert run(store.job_last_run("digest")) == bot.clock()


# --- дайджест: обложка ---------------------------------------------------------

def test_build_digest_starts_with_cover():
    bot, _, _, _ = make()
    messages = run(content.build_digest(bot))
    first = messages[0]
    assert first.photo is not None and first.photo.startswith(b"\x89PNG")
    assert first.text == "<b>Дайджест · Дельта · 10–16 окт</b>"
    assert all(m.photo is None for m in messages[1:])
    assert messages[1].text.startswith("🏆 <b>НАШИ ЛУЧШИЕ</b>")


def test_send_digest_delivers_cover_and_text_to_everyone():
    bot, telegram, _, store = make()
    run(content.send_digest(bot))
    photos = telegram.of("photo")
    assert {call[1] for call in photos} == {PERSON, GROUP} and len(photos) == 2
    assert isinstance(photos[0][2], bytes)                  # первому — загрузка
    assert photos[1][2] == f"big-{photos[0][4]}"            # второму — file_id
    assert group_texts(telegram) == sent_texts(telegram, PERSON)
    assert group_texts(telegram)[0].startswith("🏆 <b>НАШИ ЛУЧШИЕ</b>")
    assert run(store.job_last_run("digest")) == bot.clock()


def test_digest_cover_draw_failure_sends_text_only(monkeypatch, caplog):
    from telegram_bot import cover

    def broken(data):
        raise MemoryError

    monkeypatch.setattr(cover, "draw", broken)
    bot, telegram, _, store = make()
    run(content.send_digest(bot))
    assert telegram.of("photo") == []
    texts = group_texts(telegram)
    assert texts[0].startswith("<b>Дайджест · Дельта · 10–16 окт</b>\n\n🏆 <b>НАШИ ЛУЧШИЕ</b>")
    assert "MemoryError" in caplog.text
    assert run(store.job_last_run("digest")) == bot.clock()


def test_cover_for_title_subtitle_rows():
    dashboard = fixture("dashboard.json")
    current = {"telegram": {"posts": 20, "views": 112000, "reactions": 1},
               "vk": {"posts": 8, "views": 15000, "reactions": 1}}
    previous = {"telegram": {"posts": 10, "views": 100000, "reactions": 1}}
    data = content.cover_for(dashboard, OUR_ID, current, previous, "10–16 окт")
    assert data.title == "Дельта"
    assert data.subtitle == "10–16 окт · просмотры за неделю"
    assert [(row.platform, row.value, row.previous) for row in data.rows] == [
        ("telegram", 112000, 100000), ("vk", 15000, None)]
    for entry in dashboard["institutions"]:
        if entry["legacyId"] == OUR_ID:
            entry["shortName"] = None
    assert content.cover_for(dashboard, OUR_ID, current, None, None).title == "Университет Дельта"
    assert content.cover_for(dashboard, OUR_ID, {}, None, None).subtitle == "просмотры за неделю"
    assert content.cover_for({}, OUR_ID, {}, None, None).title == f"вуз №{OUR_ID}"


def test_digest_without_any_platform_has_no_cover(monkeypatch):
    from telegram_bot import cover

    draws = []
    monkeypatch.setattr(cover, "draw", lambda data: draws.append(data) or b"png")
    bot, telegram, source, _ = make()

    async def no_stats() -> dict:
        body = fixture("dashboard.json")
        body["stats"] = []
        return body

    source.dashboard = no_stats
    messages = run(content.build_digest(bot))
    assert all(m.photo is None for m in messages) and draws == []
    assert messages[0].text.startswith("<b>Дайджест · Дельта · 10–16 окт</b>")
    run(content.send_digest(bot))
    assert telegram.of("photo") == [] and draws == []
    assert group_texts(telegram)[0].startswith("<b>Дайджест · Дельта · 10–16 окт</b>")


def test_cover_import_and_draw_run_off_the_event_loop(monkeypatch):
    import threading

    from telegram_bot import cover

    main = threading.get_ident()
    threads = []
    real_cover_for = content.cover_for

    def spy_cover_for(*args):
        threads.append(("cover_for", threading.get_ident()))
        return real_cover_for(*args)

    def spy_draw(data):
        threads.append(("draw", threading.get_ident()))
        return b"png"

    monkeypatch.setattr(content, "cover_for", spy_cover_for)
    monkeypatch.setattr(cover, "draw", spy_draw)
    bot, _, _, _ = make()
    messages = run(content.build_digest(bot))
    assert messages[0].photo == b"png"
    assert [name for name, _ in threads] == ["cover_for", "draw"]
    assert all(ident != main for _, ident in threads)   # импорт Pillow и рисование — в потоке
