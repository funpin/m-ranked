from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import random
from uuid import UUID

from anomaly_analysis.v2.account_findings import (
    PACK_MIN_POSTS, REGULAR_MIN_POSTS, LedgerPost, _regular_stats, findings, pack_ratio, summary,
)
from anomaly_analysis.v2.tail_ledger import Point, TailLedger

TODAY = date(2026, 10, 6)
HOUR = 3600


def post(account: int, index: int, h2: tuple[int, int], h24: tuple[int, int], h72: tuple[int, int] | None = None,
         platform: str = "max", repost: bool = False) -> LedgerPost:
    marks = {"h2": Point(2 * HOUR, *h2), "h24": Point(24 * HOUR, *h24)}
    if h72 is not None:
        marks["h72"] = Point(72 * HOUR, *h72)
    published = datetime(2026, 9, 7, 9, tzinfo=timezone.utc) + timedelta(hours=7 * index)
    return LedgerPost(UUID(int=account * 10_000 + index), UUID(int=account), platform, published, repost,
                      TailLedger(None, None, None, marks=marks))


def organic(account: int, count: int, rng: random.Random, platform: str = "max") -> list[LedgerPost]:
    """Живая аудитория: доля в первые 2 ч чуть выше суточной, реакции растут с охватом."""
    posts = []
    for index in range(count):
        v2 = rng.randint(200, 400)
        v24 = v2 + rng.randint(300, 600)
        quality = rng.lognormvariate(0, 0.4)
        r2 = round(v2 * 0.08 * quality)
        r24 = r2 + round((v24 - v2) * 0.05 * quality)
        posts.append(post(account, index, (v2, r2), (v24, r24), (v24 + 100, r24 + 3), platform))
    return posts


def test_pack_ratio_compares_first_two_hours_with_the_rest_of_the_day():
    # 60 реакций на 250 просмотров, затем 4 на 400: доля упала в ~24 раза.
    ratio, *_ = pack_ratio(post(1, 0, (250, 60), (650, 64)).ledger)
    assert 20 < ratio < 30
    assert pack_ratio(post(1, 0, (5, 1), (10, 2)).ledger) is None


def test_pack_lasting_several_hours_is_measured_at_six_hours():
    # ГУАП в MAX: 36 реакций на 220 просмотров к 2 ч, 59 на 334 к 6 ч, затем
    # +1 на 120. Двухчасовое окно делило пакет пополам и видело лишь ~1,6 раза.
    ledger = TailLedger(None, None, None, marks={
        "h2": Point(2 * HOUR, 221, 36), "h6": Point(6 * HOUR, 334, 59), "h24": Point(24 * HOUR, 452, 60)})
    ratio, r1, v1, *_ = pack_ratio(ledger)
    assert (r1, v1) == (59, 334) and ratio > 20


def test_repeated_early_pack_is_found_and_names_its_posts():
    rng = random.Random(3)
    cohort = [item for account in range(2, 12) for item in organic(account, 40, rng)]
    packed = [post(1, index, (250, 60 + index % 7), (650, 62 + index % 7), (800, 64)) for index in range(40)]
    result = findings(cohort + packed, TODAY)
    (finding,) = [item for item in result if item.kind == "early_pack"]
    assert finding.account_id == UUID(int=1) and finding.status == 2
    assert set(finding.members) == {item.publication_id for item in packed}
    assert finding.metrics["cohort"]["median"] < 3 and finding.metrics["median"] > 10
    assert "первые часы" in summary(finding)


def test_too_few_posts_or_organic_accounts_give_no_finding():
    rng = random.Random(5)
    few = [post(1, index, (250, 60), (650, 62)) for index in range(PACK_MIN_POSTS - 1)]
    cohort = [item for account in range(2, 12) for item in organic(account, 40, rng)]
    assert findings(few + cohort, TODAY) == []


def test_regular_reactions_flag_counts_that_ignore_post_appeal():
    rng = random.Random(7)
    cohort = [item for account in range(2, 12) for item in organic(account, 40, rng)]
    # Охват от 400 до 1 300, а реакций к 72 часам — пуассоновский шум вокруг 75.
    regular = []
    for index in range(REGULAR_MIN_POSTS + 10):
        views = rng.randint(400, 1300)
        reactions = max(1, round(rng.gauss(75, 75 ** 0.5)))
        regular.append(post(1, index, (views // 3, reactions // 2), (views, reactions - 2), (views + 50, reactions)))
    result = findings(cohort + regular, TODAY)
    kinds = {(item.account_id, item.kind) for item in result}
    assert (UUID(int=1), "regular_reactions") in kinds
    assert not any(account != UUID(int=1) for account, _ in kinds)


def daily_posts(account: int, days: int, per_day: int, reactions, rng: random.Random,
                platform: str = "max", views=None, institution: int | None = None) -> list[LedgerPost]:
    """По `per_day` постов в сутки с 08.09 (10:00–22:00 МСК); `reactions(day, rng)` — реакции к 72 ч."""
    posts = []
    for day in range(days):
        for slot in range(per_day):
            index = day * per_day + slot
            published = datetime(2026, 9, 8, 7, tzinfo=timezone.utc) + timedelta(days=day, hours=2 * slot)
            views_72 = views(day, rng) if views else rng.randint(700, 1100)
            r72 = reactions(day, rng)
            marks = {"h2": Point(2 * HOUR, views_72 // 3, r72 // 2),
                     "h24": Point(24 * HOUR, views_72 - 20, max(0, r72 - 2)), "h72": Point(72 * HOUR, views_72, r72)}
            posts.append(LedgerPost(UUID(int=account * 10_000 + index), UUID(int=account), platform, published,
                                    False, TailLedger(None, None, None, marks=marks),
                                    UUID(int=10**6 + institution) if institution is not None else None))
    return posts


def _poisson(mean: float, rng: random.Random) -> int:
    return max(1, round(rng.gauss(mean, mean ** 0.5)))


def test_regular_reactions_within_a_day_survive_a_change_of_level():
    # ЮЗГУ в MAX: ~95 реакций на каждом посте, с 19.09 — ~250; внутри дня —
    # только пуассоновский шум. Разброс за месяц раздут скачком уровня.
    rng = random.Random(11)
    cohort = [item for account in range(2, 12) for item in organic(account, 40, rng)]
    stepped = daily_posts(1, 25, 6, lambda day, rng: _poisson(95 if day < 11 else 250, rng), rng)
    (finding,) = [item for item in findings(cohort + stepped, TODAY) if item.kind == "regular_reactions"]
    assert finding.account_id == UUID(int=1)
    assert finding.metrics["measure"] == "day" and finding.metrics["windowExtra"] > 0.3
    assert finding.metrics["dayExtra"] <= 0.08 and "внутри" in summary(finding)


def test_fewer_reactions_differences_than_chance_are_a_persistent_finding():
    rng = random.Random(13)
    flat = daily_posts(1, 20, 5, lambda day, rng: 100 + rng.randint(-2, 2), rng)
    (finding,) = [item for item in findings(flat, TODAY) if item.kind == "regular_reactions"]
    assert finding.metrics["subPoisson"] and finding.status == 2
    assert "меньше, чем дал бы случай" in summary(finding)


def test_one_post_a_day_keeps_the_window_measure():
    rng = random.Random(17)
    single = daily_posts(1, REGULAR_MIN_POSTS + 2, 1, lambda day, rng: _poisson(75, rng), rng)
    stats = _regular_stats(single)
    assert stats["dayExtra"] is None and stats["measure"] == "window" and stats["days"] == 0


def test_reposts_count_for_packs_but_not_for_regularity():
    packed = [post(1, index, (250, 60), (650, 62), (800, 64), repost=True) for index in range(40)]
    result = findings(packed, TODAY)
    assert {item.kind for item in result} == {"early_pack"}


def test_persistently_unusual_tail_profile_becomes_a_finding_with_late_posts():
    members = {UUID(int=1): [UUID(int=11), UUID(int=12)]}
    tail = {UUID(int=1): ("max", 2, {"ratio": 0.65}), UUID(int=2): ("max", 1, {"ratio": 0.4})}
    # Пост с округлёнными счётчиками без признака: по сводке поздняя доля втрое выше ранней.
    late = post(1, 0, (250, 20), (600, 30))
    late = LedgerPost(late.publication_id, late.account_id, late.platform, late.published_at, False,
                      TailLedger(Point(24 * HOUR, 600, 30), Point(4 * 24 * HOUR, 700, 31), Point(10 * 24 * HOUR, 900, 61)))
    result = findings([late], TODAY, members, tail)
    (finding,) = result
    assert finding.kind == "late_engagement"
    assert finding.members == (UUID(int=11), UUID(int=12), late.publication_id)


def test_posts_outside_the_thirty_day_window_are_ignored():
    old = [post(1, index, (250, 60), (650, 62)) for index in range(40)]
    shifted = [LedgerPost(item.publication_id, item.account_id, item.platform,
                          item.published_at - timedelta(days=60), item.is_repost, item.ledger) for item in old]
    assert findings(shifted, TODAY) == []


def test_posts_that_gain_reactions_days_later_are_a_finding():
    from anomaly_analysis.v2.account_findings import headline, figure, with_texts
    rng = random.Random(9)
    cohort = [item for account in range(2, 12) for item in organic(account, 40, rng)]
    boosted = []
    for index in range(30):
        base = post(1, index, (300, 8), (600, 10), (900, 12))
        # К суткам 10 реакций, к 10-м суткам — 360: докачка через дни.
        ledger = TailLedger(Point(24 * HOUR, 600, 10), Point(4 * 24 * HOUR, 900, 12), Point(10 * 24 * HOUR, 7000, 360),
                            marks=base.ledger.marks)
        boosted.append(LedgerPost(base.publication_id, base.account_id, "vk", base.published_at, False, ledger))
    organic_vk = [LedgerPost(item.publication_id, item.account_id, "vk", item.published_at, False,
                             TailLedger(item.ledger.marks["h24"], item.ledger.marks["h72"], item.ledger.marks["h72"],
                                        marks=item.ledger.marks)) for item in cohort]
    result = findings(boosted + organic_vk, TODAY)
    (finding,) = [item for item in result if item.kind == "late_growth"]
    assert finding.account_id == UUID(int=1) and finding.status == 2 and len(finding.members) == 30
    texts = with_texts(finding).metrics
    assert texts["headline"].startswith("У 100 % постов") and texts["figure"]["unit"] == "percent"
    assert texts["figure"]["typical"] == 0.0


def _waves(account: int, days: list[int], posts_per_day: int, platform: str = "vk"):
    """Признак 8 у `posts_per_day` постов аккаунта утром каждого из дней окна (номер дня от начала)."""
    from anomaly_analysis.v2.account_findings import SynchronyEvent
    start = datetime(2026, 9, 6, 7, tzinfo=timezone.utc)   # 10:00 МСК, первый день окна
    return [SynchronyEvent(UUID(int=account), platform, UUID(int=account * 10_000 + post_index),
                           start + timedelta(days=day, minutes=post_index % 3 * 30))
            for day in days for post_index in range(posts_per_day)]


def _vk(account: int, count: int, rng: random.Random) -> list[LedgerPost]:
    return [LedgerPost(item.publication_id, item.account_id, "vk", item.published_at, False, item.ledger)
            for item in organic(account, count, rng)]


def test_reaction_waves_over_much_of_the_wall_on_many_days_are_a_finding():
    from anomaly_analysis.v2.account_findings import headline, with_texts
    rng = random.Random(11)
    posts = [item for account in range(1, 12) for item in _vk(account, 40, rng)]
    # Аккаунт 1: шесть утр за месяц признак 8 сразу у 12 постов (ЮЗГУ ВК с 21.09).
    # У других — редкие совпадения у трёх постов: обычный общий толчок.
    events = _waves(1, [2, 6, 10, 17, 21, 25], 12) + _waves(2, [4], 3) + _waves(3, [12, 20], 4)
    result = findings(posts, TODAY, synchrony=events)
    (finding,) = [item for item in result if item.kind == "synchronous_waves"]
    assert finding.account_id == UUID(int=1) and finding.status == 2
    assert finding.metrics["days"] == 6 and finding.metrics["maxPosts"] == 12
    assert set(finding.members) == {UUID(int=10_000 + index) for index in range(12)}
    assert finding.metrics["cohort"]["median"] == 0
    texts = with_texts(finding).metrics
    assert texts["figure"]["unit"] == "percent" and texts["figure"]["value"] == 0.3
    assert headline(finding) == "6 дней с волной реакций сразу на многих постах"


def test_waves_in_one_half_of_the_window_are_not_yet_persistent():
    rng = random.Random(12)
    posts = [item for account in range(1, 6) for item in _vk(account, 40, rng)]
    result = findings(posts, TODAY, synchrony=_waves(1, [17, 20, 23, 26], 12))
    (finding,) = [item for item in result if item.kind == "synchronous_waves"]
    assert finding.status == 1


def test_few_or_small_waves_are_not_a_finding():
    rng = random.Random(13)
    posts = [item for account in range(1, 6) for item in _vk(account, 40, rng)]
    # Три волны — мало; много дней, но по 9 постов — не волна по всей стене.
    events = _waves(1, [3, 12, 22], 15) + _waves(2, list(range(0, 30, 2)), 9)
    assert not [item for item in findings(posts, TODAY, synchrony=events) if item.kind == "synchronous_waves"]


def _shift(account: int, start_day: int, rng: random.Random, *, until_day: int = 99, days: int = 25, high: float = 240,
           platform: str = "max", institution: int | None = None, views=None) -> list[LedgerPost]:
    return daily_posts(account, days, 5, lambda day, rng: _poisson(high if start_day <= day < until_day else 95, rng),
                       rng, platform, views, institution)


def _kind(result, kind: str, account: int = 1):
    return [item for item in result if item.kind == kind and item.account_id == UUID(int=account)]


def test_engagement_rising_from_a_date_without_more_views_is_a_finding():
    rng = random.Random(21)
    cohort = [item for account in range(2, 12) for item in organic(account, 40, rng)]
    (finding,) = _kind(findings(cohort + _shift(1, 11, rng), TODAY), "engagement_shift")
    data = finding.metrics
    assert finding.status == 2 and data["cut"] == "2026-09-19"
    assert data["ratio"] > 2 and data["separation"] >= 0.9 and 0.8 < data["viewsRatio"] < 1.25
    assert len(finding.members) >= 0.9 * data["after"]
    assert "19.09" in summary(finding) and not _kind(findings(cohort, TODAY), "engagement_shift", 2)


def test_a_rise_that_fades_by_the_end_of_the_window_is_not_persistent():
    rng = random.Random(23)
    (finding,) = _kind(findings(_shift(1, 11, rng, until_day=21, days=28), TODAY), "engagement_shift")
    assert finding.status == 1


def test_engagement_rising_because_views_collapsed_or_slowly_is_not_a_finding():
    rng = random.Random(25)
    collapsed = daily_posts(1, 25, 5, lambda day, rng: _poisson(95, rng), rng,
                            views=lambda day, rng: rng.randint(700, 1100) if day < 11 else rng.randint(70, 110))
    gradual = daily_posts(2, 25, 5, lambda day, rng: _poisson(95 * (1 + 0.5 * day / 25), rng), rng)
    assert not [item for item in findings(collapsed + gradual, TODAY) if item.kind == "engagement_shift"]


def test_the_same_rise_on_the_institutions_other_platforms_is_listed_as_support():
    rng = random.Random(27)
    posts = (_shift(1, 11, rng, institution=7) + _shift(2, 12, rng, platform="vk", institution=7, high=280)
             + _shift(3, 11, rng, platform="vk", institution=8) + _shift(4, 11, rng, platform="telegram", institution=7,
                                                                       until_day=0))
    (finding,) = _kind(findings(posts, TODAY), "engagement_shift")
    assert [(item["platform"], item["cut"]) for item in finding.metrics["corroboration"]] == [("vk", "2026-09-20")]
    assert "VK" in summary(finding)


def _diurnal(night_start_utc: int, day: int, night: int) -> list[int]:
    """Почасовой профиль: шесть часов с `night_start_utc` — по `night`, остальные — по `day`."""
    hours = [day] * 24
    for offset in range(6):
        hours[(night_start_utc + offset) % 24] = night
    return hours


def night_posts(account: int, count: int, views: list[int], reactions, platform: str = "max") -> list[LedgerPost]:
    posts = []
    for index in range(count):
        published = datetime(2026, 9, 8, 9, tzinfo=timezone.utc) + timedelta(hours=7 * index)
        hourly = reactions(index) if callable(reactions) else reactions
        ledger = TailLedger(None, None, None, marks={"h72": Point(72 * HOUR, 900, 90)},
                            hours=(tuple(views), tuple(hourly)))
        posts.append(LedgerPost(UUID(int=account * 10_000 + index), UUID(int=account), platform, published,
                                False, ledger))
    return posts


# Московская аудитория: ночь 01–07 МСК = 22–04 UTC.
MOSCOW_VIEWS = _diurnal(22, 20, 1)
FOLLOWING = [round(value / 10) for value in MOSCOW_VIEWS]


def test_reactions_at_night_while_views_sleep_are_a_finding():
    cohort = [item for account in range(2, 8) for item in night_posts(account, 40, MOSCOW_VIEWS, FOLLOWING)]
    # МАИ в MAX: 36 % поздних реакций ночью при 3 % просмотров.
    bot = night_posts(1, 40, MOSCOW_VIEWS, _diurnal(22, 2, 3))
    (finding,) = _kind(findings(cohort + bot, TODAY), "night_reactions")
    data = finding.metrics
    assert finding.status == 2 and data["nightStartMsk"] == 1 and data["shiftHours"] == 0
    assert data["reactionShare"] > 0.3 and data["viewShare"] < 0.05
    assert len(finding.members) == 40 and "01:00–07:00 МСК" in summary(finding)
    assert not [item for item in findings(cohort, TODAY) if item.kind == "night_reactions"]


def test_the_audience_night_follows_its_own_time_zone():
    # Иркутск (UTC+8): ночь 01–07 местного = 17–23 UTC = 20:00–02:00 МСК.
    local = _diurnal(17, 20, 1)
    honest = night_posts(1, 40, local, [round(value / 10) for value in local])
    assert not [item for item in findings(honest, TODAY) if item.kind == "night_reactions"]
    bot = night_posts(2, 40, local, _diurnal(17, 2, 3))
    (finding,) = _kind(findings(bot, TODAY), "night_reactions", 2)
    assert finding.metrics["nightStartMsk"] == 20 and finding.metrics["shiftHours"] == -5
    assert "другом часовом поясе" in summary(finding)


def test_no_night_in_the_views_or_hourless_ledgers_give_no_finding():
    flat = night_posts(1, 40, [10] * 24, _diurnal(22, 2, 3))
    old = [LedgerPost(item.publication_id, UUID(int=2), item.platform, item.published_at, False,
                      TailLedger(None, None, None, marks=item.ledger.marks)) for item in night_posts(2, 40, MOSCOW_VIEWS, FOLLOWING)]
    assert not [item for item in findings(flat + old, TODAY) if item.kind == "night_reactions"]


def test_night_reactions_in_one_half_of_the_window_are_not_yet_persistent():
    first_half = night_posts(1, 40, MOSCOW_VIEWS, lambda index: _diurnal(22, 2, 3) if index < 20 else FOLLOWING)
    (finding,) = _kind(findings(first_half, TODAY), "night_reactions")
    assert finding.status == 1


def test_a_night_no_russian_time_zone_could_have_is_not_a_night():
    # Провал просмотров в 15–21 МСК: ни в одном часовом поясе России это не ночь
    # (КБГУ во ВКонтакте — артефакт выдачи, а не аудитория).
    afternoon = _diurnal(12, 20, 1)
    posts = night_posts(1, 40, afternoon, _diurnal(12, 2, 3))
    assert not [item for item in findings(posts, TODAY) if item.kind == "night_reactions"]


def test_a_gradual_rise_on_another_platform_four_days_apart_still_supports():
    rng = random.Random(29)
    posts = _shift(1, 11, rng, institution=7) + _shift(2, 15, rng, platform="vk", institution=7, high=280)
    (finding,) = _kind(findings(posts, TODAY), "engagement_shift")
    assert [item["platform"] for item in finding.metrics["corroboration"]] == ["vk"]


def test_headlines_name_only_what_the_numbers_show():
    from anomaly_analysis.v2.account_findings import headline
    rng = random.Random(31)
    (shift,) = _kind(findings(_shift(1, 11, rng), TODAY), "engagement_shift")
    assert headline(shift).endswith("при тех же просмотрах") and shift.title == "Скачок доли реакций на просмотр"
    grown = _shift(1, 11, rng, high=500, views=lambda day, rng: round(rng.randint(700, 1100) * (1 if day < 11 else 1.6)))
    (shift,) = _kind(findings(grown, TODAY), "engagement_shift")
    assert "при тех же просмотрах" not in headline(shift) and "просмотры" in headline(shift)
    stepped = daily_posts(1, 25, 6, lambda day, rng: _poisson(95 if day < 11 else 250, rng), rng)
    (regular,) = _kind(findings(stepped, TODAY), "regular_reactions")
    assert headline(regular) == "Посты одного дня получают почти одинаковое число реакций"
    bot = night_posts(1, 40, MOSCOW_VIEWS, _diurnal(22, 2, 3))
    cohort = [item for account in range(2, 8) for item in night_posts(account, 40, MOSCOW_VIEWS, _diurnal(22, 20, 2))]
    (night,) = _kind(findings(bot + cohort, TODAY), "night_reactions")
    assert "в 0," not in summary(night) and "у типичного аккаунта площадки отношение" in summary(night)
