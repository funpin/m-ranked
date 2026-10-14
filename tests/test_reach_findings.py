"""Аккаунтные находки по охватам: пакеты и волны просмотров, суточный ритм, много постов уровня 3."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from anomaly_analysis.v2.reach_findings import PostLevel, level3_findings, view_pack_findings

TODAY = date(2026, 10, 8)


def posts(account: int, count: int, *, platform="vk", step_hours=7):
    """count чистых постов через `step_hours`, с 08.09."""
    start = datetime(2026, 9, 8, 9, tzinfo=timezone.utc)
    return [PostLevel(UUID(int=account * 10_000 + i), UUID(int=account), platform,
                      start + timedelta(hours=step_hours * i), 0, frozenset(), False) for i in range(count)]


def spread(account, count, k, *, level3=False, packs=False, patterns=(9, 14), **kw):
    """k постов из count с признаком, равномерно по окну."""
    marked = set(range(0, count, max(1, count // k)))
    return [PostLevel(p.publication_id, p.account_id, p.platform, p.published_at,
                      3 if level3 and i in marked else 0,
                      frozenset(patterns) if level3 and i in marked else frozenset(),
                      packs and i in marked) for i, p in enumerate(posts(account, count, **kw))]


def cohort(n=12, count=60):
    return [p for a in range(2, 2 + n) for p in spread(a, count, 1, level3=True)]


def of(found, account=1):
    return [f for f in found if f.account_id == UUID(int=account)]


def test_many_level3_posts_in_both_halves_are_a_persistent_finding():
    (finding,) = of(level3_findings(cohort() + spread(1, 80, 40, level3=True), TODAY))
    assert finding.kind == "level3_share" and finding.status == 2 and len(finding.members) == 40


def test_level3_of_a_single_pattern_is_at_most_status_one():
    (finding,) = of(level3_findings(cohort() + spread(1, 80, 40, level3=True, patterns=(9,)), TODAY))
    assert finding.status == 1


def test_few_posts_give_no_level3_finding():
    assert not of(level3_findings(cohort() + spread(1, 15, 10, level3=True), TODAY))


def test_ordinary_share_of_level3_is_not_a_finding():
    assert not of(level3_findings(cohort() + spread(1, 60, 1, level3=True), TODAY))


def test_repeated_view_packs_are_a_finding():
    (finding,) = of(view_pack_findings(cohort() + spread(1, 80, 25, packs=True), TODAY))
    assert finding.kind == "view_packs" and finding.status == 2


def test_packs_in_one_week_only_are_not_persistent():
    early = datetime(2026, 9, 15, tzinfo=timezone.utc)
    items = [PostLevel(p.publication_id, p.account_id, p.platform, p.published_at, 0, frozenset(),
                       p.view_pack and p.published_at < early) for p in spread(1, 80, 80, packs=True)]
    found = of(view_pack_findings(cohort() + items, TODAY))
    assert found and all(f.status == 1 for f in found)


def test_a_few_packs_are_not_a_finding():
    assert not of(view_pack_findings(cohort() + spread(1, 80, 4, packs=True), TODAY))


from anomaly_analysis.v2.account_findings import LedgerPost  # noqa: E402
from anomaly_analysis.v2.reach_findings import (  # noqa: E402
    early_response_findings, flat_day_findings, promotion_findings, wave_findings,
)
from anomaly_analysis.v2.tail_ledger import MOSCOW as MOSCOW_TZ, Point, TailLedger  # noqa: E402

BASE = datetime(2026, 9, 8, 9, tzinfo=timezone.utc)


def wall(account, count=60, waves=(), platform="vk", late=(5000, 100)):
    """count постов по 12 ч; волна — (час от BASE, сколько последних постов, просмотров на пост)."""
    items = []
    for i in range(count):
        published = BASE + timedelta(hours=12 * i)
        surges = []
        for at_hour, last_n, views in waves:
            moment = BASE + timedelta(hours=at_hour)
            older = [j for j in range(count) if BASE + timedelta(hours=12 * j) <= moment - timedelta(days=1)]
            if i in older[-last_n:]:
                surges.append((int(moment.timestamp() // 3600), views, 0))
        ledger = TailLedger(Point(86400, 1000, 30), Point(4 * 86400, 1200, 32),
                            Point(10 * 86400, 1200 + late[0] // count, 32 + late[1] // count), surges=tuple(surges))
        items.append(LedgerPost(UUID(int=account * 10_000 + i), UUID(int=account), platform, published, False, ledger))
    return items


WAVES = [(24 * 12 + h, 15, 1300) for h in range(10)] + [(24 * 25 + h, 15, 1300) for h in range(6)]


def test_waves_over_the_latest_posts_on_two_weeks_are_persistent():
    others = [p for a in range(2, 12) for p in wall(a)]
    (finding,) = of(wave_findings(wall(1, waves=WAVES) + others, TODAY))
    assert finding.kind == "view_waves" and finding.status == 2
    assert finding.metrics["days"] == 2 and finding.metrics["hours"] == 16 and finding.metrics["latestN"] == 15


def test_scattered_surges_are_not_a_wave():
    # 12 постов в один час, но не последние подряд: каждый третий из старых.
    hour = int((BASE + timedelta(days=20)).timestamp() // 3600)
    items = [LedgerPost(p.publication_id, p.account_id, p.platform, p.published_at, False,
                        TailLedger(p.ledger.early, p.ledger.start, p.ledger.end,
                                   surges=((hour, 900, 0),) if k % 3 == 0 and k < 36 else ()))
             for k, p in enumerate(wall(1))]
    assert not of(wave_findings(items, TODAY))


def test_hour_shared_by_most_accounts_of_the_platform_is_not_a_wave():
    everyone = [p for a in range(1, 12) for p in wall(a, waves=[(24 * 15, 20, 800)])]
    assert wave_findings(everyone, TODAY) == []


def test_wave_with_ordinary_response_is_not_a_finding():
    # Тот же приток, но реакции идут как у поздних просмотров аккаунта.
    items = wall(1, waves=WAVES)
    items = [LedgerPost(p.publication_id, p.account_id, p.platform, p.published_at, False,
                        TailLedger(p.ledger.early, p.ledger.start, p.ledger.end,
                                   surges=tuple((h, v, v // 50) for h, v, _ in p.ledger.surges)))
             for p in items]
    assert not of(wave_findings(items + [p for a in range(2, 12) for p in wall(a)], TODAY))


def flat(account, night_share, count=40, platform="max"):
    hours_views = [100] * 24
    for hour in range(20, 24):
        hours_views[hour] = int(100 * night_share)
    ledger = TailLedger(Point(86400, 500, 10), None, None, hours=(tuple(hours_views), (0,) * 24))
    return [LedgerPost(UUID(int=account * 10_000 + i), UUID(int=account), platform,
                       BASE + timedelta(hours=17 * i), False, ledger) for i in range(count)]


def test_views_without_a_night_trough_are_a_finding():
    others = [p for a in range(2, 12) for p in flat(a, 0.15)]
    (finding,) = of(flat_day_findings(others + flat(1, 0.9), TODAY))
    assert finding.kind == "flat_daily_views" and finding.metrics["amplitude"] >= 0.5 and finding.status == 2


def test_ordinary_night_trough_is_not_a_finding():
    others = [p for a in range(2, 12) for p in flat(a, 0.15)]
    assert not of(flat_day_findings(others + flat(1, 0.2), TODAY))


def test_small_audience_gives_no_rhythm_finding():
    others = [p for a in range(2, 12) for p in flat(a, 0.15)]
    assert not of(flat_day_findings(others + flat(1, 0.9, count=5), TODAY))


def campaign(account, count=40, promoted=(), platform="vk", response=0.0, night=0.1, excess=30.0):
    """count постов ВК по 18 ч с 10.09; продвигаемые получают на вторые–пятые сутки в excess раз
    больше просмотров, response — доля реакций от обычной, night — доля ночных просмотров.
    Обычный пост: сутки k — 400/k просмотров, 4 % реакций, ночью 8 %."""
    start = datetime(2026, 9, 10, 9, tzinfo=timezone.utc)
    items = []
    for i in range(count):
        published = start + timedelta(hours=18 * i)
        first = published.astimezone(MOSCOW_TZ).date()
        days = []
        for k in range(1, 15):
            day = first + timedelta(days=k)
            if day >= TODAY:
                break
            views = 400 // k
            reactions, night_views = views * 4 // 100, views * 8 // 100
            if i in promoted and 2 <= k <= 5:
                views = int(views * excess)
                reactions = int(views * 0.04 * response)
                night_views = int(views * night)
            days.append((day.isoformat(), views, reactions, night_views))
        ledger = TailLedger(Point(86400, 1000, 30), None, None, days=tuple(days))
        items.append(LedgerPost(UUID(int=account * 10_000 + i), UUID(int=account), platform, published, False, ledger))
    return items


def test_promoted_posts_are_marked_with_context_status():
    others = [p for a in range(2, 12) for p in campaign(a)]
    (finding,) = of(promotion_findings(campaign(1, promoted={5, 6, 7, 30}) + others, TODAY))
    assert finding.kind == "promotion" and finding.status == 1
    assert {member.int % 10_000 for member in finding.members} == {5, 6, 7, 30}
    assert finding.metrics["days"] >= 4 and finding.metrics["excessMedian"] >= 5


def test_one_stray_reaction_does_not_break_a_promotion_run():
    """Отклик судится по всей серии: МФТИ №58974 — 1 реакция на 903 просмотра на 11-е сутки."""
    others = [p for a in range(2, 12) for p in campaign(a)]
    items = campaign(1, promoted={5, 6})
    post = items[5]
    days = tuple((day, views, 40 if index in (2, 4) else reactions, night)
                 for index, (day, views, reactions, night) in enumerate(post.ledger.days))
    items[5] = LedgerPost(post.publication_id, post.account_id, post.platform, post.published_at, False,
                          TailLedger(post.ledger.early, None, None, days=days))
    (finding,) = of(promotion_findings(items + others, TODAY))
    assert {member.int % 10_000 for member in finding.members} == {5, 6}


def test_promotion_needs_low_response_and_a_night_trough():
    others = [p for a in range(2, 12) for p in campaign(a)]
    assert not of(promotion_findings(campaign(1, promoted={5, 6}, response=1.0) + others, TODAY))
    # Ровный круглосуточный пакет: ночью четверть суточных просмотров.
    assert not of(promotion_findings(campaign(1, promoted={5, 6}, night=0.25) + others, TODAY))
    assert not of(promotion_findings(campaign(1, promoted={5, 6}, excess=3.0) + others, TODAY))


def test_promotion_is_vk_only_and_not_a_platform_event():
    telegram = [p for a in range(2, 12) for p in campaign(a, platform="telegram")]
    assert not of(promotion_findings(campaign(1, promoted={5, 6}, platform="telegram") + telegram, TODAY))
    # Те же сутки у всех аккаунтов площадки — событие площадки.
    everyone = [p for a in range(1, 12) for p in campaign(a, promoted={5, 6})]
    assert not of(promotion_findings(everyone, TODAY))


def test_every_reach_kind_has_words_for_the_api():
    from anomaly_analysis.v2.account_findings import with_texts
    others = [p for a in range(2, 12) for p in wall(a)]
    found = (of(wave_findings(wall(1, waves=WAVES) + others, TODAY))
             + of(level3_findings(cohort() + spread(1, 80, 40, level3=True), TODAY))
             + of(view_pack_findings(cohort() + spread(1, 80, 25, packs=True), TODAY))
             + of(flat_day_findings([p for a in range(2, 12) for p in flat(a, 0.15)] + flat(1, 0.9), TODAY))
             + of(promotion_findings(campaign(1, promoted={5, 6}) + [p for a in range(2, 12) for p in campaign(a)],
                                     TODAY))
             + of(early_response_findings(early(1, quick=set(range(0, 20, 2)))
                                          + [p for a in range(2, 12) for p in early(a)], TODAY)))
    assert {f.kind for f in found} == {"view_waves", "level3_share", "view_packs", "flat_daily_views", "promotion",
                                       "early_response"}
    for finding in found:
        metrics = with_texts(finding).metrics
        assert finding.title and metrics["summary"] and metrics["headline"] and metrics["alternatives"]
        assert metrics["statusLabel"] and "накрут" not in (metrics["summary"] + metrics["headline"]).lower()


def test_findings_method_version_is_bumped():
    from anomaly_analysis.v2.account_findings import METHOD_VERSION
    assert METHOD_VERSION == "account-findings-v6"


def early(account, count=20, quick=(), platform="vk", publication_type="photo", views=60):
    """count постов по 30 ч с 12.09; у `quick` на первом замере реакций 60 % просмотров, у прочих 4 %."""
    start = datetime(2026, 9, 12, 9, tzinfo=timezone.utc)
    items = []
    for i in range(count):
        reactions = int(views * (0.6 if i in quick else 0.04))
        ledger = TailLedger(None, None, None, marks={"first": Point(600, views, reactions)})
        items.append(LedgerPost(UUID(int=account * 10_000 + i), UUID(int=account), platform,
                                start + timedelta(hours=30 * i), False, ledger, None, publication_type))
    return items


def test_early_response_on_many_posts_is_a_persistent_finding():
    others = [p for a in range(2, 12) for p in early(a)]
    (finding,) = of(early_response_findings(early(1, quick=set(range(0, 20, 2))) + others, TODAY))
    assert finding.kind == "early_response" and finding.status == 2
    assert finding.metrics["early"] == 10 and finding.metrics["share"] == 0.5 and finding.metrics["cohortP90"] == 0
    assert {member.int % 10_000 for member in finding.members} == set(range(0, 20, 2))


def test_early_response_in_one_half_only_is_not_persistent():
    others = [p for a in range(2, 12) for p in early(a)]
    (finding,) = of(early_response_findings(early(1, quick={0, 1, 2, 3, 4}) + others, TODAY))
    assert finding.status == 1


def test_early_response_ignores_clips_small_first_readings_and_few_posts():
    others = [p for a in range(2, 12) for p in early(a)]
    everything = set(range(20))
    assert not of(early_response_findings(early(1, quick=everything, publication_type="video") + others, TODAY))
    assert not of(early_response_findings(early(1, quick=everything, views=19) + others, TODAY))
    assert not of(early_response_findings(early(1, count=9, quick=everything) + others, TODAY))
    assert not of(early_response_findings(early(1, quick={0, 1}) + others, TODAY))


def test_early_response_is_judged_against_the_platform():
    # У двух аккаунтов площадки из десяти ранний отклик ещё чаще: 90-й перцентиль выше.
    others = [p for a in range(2, 12) for p in early(a, quick=set(range(14)) if a < 4 else set())]
    assert not of(early_response_findings(early(1, quick=set(range(0, 20, 2))) + others, TODAY))
    telegram = [p for a in range(2, 12) for p in early(a, platform="telegram")]
    assert not of(early_response_findings(early(1, quick=set(range(20)), platform="telegram") + telegram, TODAY))
