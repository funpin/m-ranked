"""Сводка позднего отклика поста и признак 13 «поздняя вовлечённость выше ранней»."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from anomaly_analysis.v2.detectors import late_engagement
from anomaly_analysis.v2.detectors.base import DetectorContext
from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.levels import assess
from anomaly_analysis.v2.series import CollectionCadence, prepare
from anomaly_analysis.v2.tail_ledger import build_ledger, ledger_from_payload
from anomaly_reference.mature_norms import synthetic_cases

HOUR, DAY = 3600, 86400
# 12:00 МСК: московские сутки поста начинаются через 12 часов после публикации.
PUBLISHED = datetime(2026, 9, 1, 9, tzinfo=timezone.utc)


def _series(points, *, platform="max", repost=False, qualities=None, uncertain=None):
    """points: (возраст в секундах, просмотры, реакции)."""
    return PostSeries(
        UUID(int=1), UUID(int=2), platform, PUBLISHED, repost,
        tuple(PUBLISHED + timedelta(seconds=age) for age, _, _ in points),
        {Metric.VIEWS: tuple(v for _, v, _ in points), Metric.REACTIONS: tuple(r for _, _, r in points)},
        qualities=qualities, interval_uncertain=uncertain or (),
    )


def _daily(start_age, days, views, reactions, step_views=0, step_reactions=0):
    return [(start_age + index * DAY, views + index * step_views, reactions + index * step_reactions)
            for index in range(days)]


def test_early_point_is_the_exact_reading_closest_to_one_day():
    ledger = build_ledger(_series([(2 * HOUR, 100, 5), (20 * HOUR, 900, 30), (25 * HOUR, 1000, 32),
                                    (29 * HOUR, 1050, 33)]))
    assert (ledger.early.views, ledger.early.reactions) == (1000, 32)
    assert build_ledger(_series([(2 * HOUR, 100, 5), (31 * HOUR, 1000, 30)])).early is None


def test_late_window_uses_exact_endpoints_and_never_counts_a_decrease_as_growth():
    points = [(24 * HOUR, 1000, 30), (3.5 * DAY, 1500, 40), (4.5 * DAY, 1520, 41), (13 * DAY, 1600, 38),
              (15 * DAY, 1700, 90)]
    ledger = build_ledger(_series(points))
    assert ledger.start.age == 3.5 * DAY and ledger.end.age == 13 * DAY
    # Реакции упали 40 → 38: прироста нет, а не −2.
    assert ledger.late == (100, 0)


def test_late_window_needs_at_least_a_day_between_its_ends():
    ledger = build_ledger(_series([(24 * HOUR, 1000, 30), (3.9 * DAY, 1500, 40), (4.6 * DAY, 1510, 41)]))
    assert ledger.late is None


def test_rounded_and_uncertain_readings_are_not_used():
    points = [(24 * HOUR, 1000, 30), (3.5 * DAY, 1500, 40), (6 * DAY, 1600, 60), (8 * DAY, 1650, 70)]
    rounded = ("exact", "exact", "rounded", "exact")
    ledger = build_ledger(_series(points, qualities={Metric.VIEWS: rounded, Metric.REACTIONS: ("exact",) * 4}))
    assert ledger.end.age == 8 * DAY
    ledger = build_ledger(_series(points, uncertain=(False, False, False, True)))
    assert ledger.end.age == 6 * DAY


def test_repost_views_belong_to_the_source_and_give_no_ledger():
    ledger = build_ledger(_series([(24 * HOUR, 1000, 30), (4 * DAY, 1500, 40), (8 * DAY, 1600, 90)], repost=True))
    assert ledger.early is None and ledger.late is None and not ledger.covered


def test_daily_growth_belongs_to_the_moscow_day_it_was_first_observed_in():
    # Замеры в 18:00 МСК каждый день с 4-го по 10-й; реакции растут на 2 в сутки.
    points = [(24 * HOUR, 1000, 30), *_daily(4 * DAY + 6 * HOUR, 7, 1500, 40, 10, 2)]
    ledger = build_ledger(_series(points))
    # Первые полные московские сутки после четырёх суток — 06.09; последние
    # покрытые — 10.09: после 11.09 замера уже нет.
    assert ledger.covered == ("2026-09-06", "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10")
    assert ledger.growth == {day: 2 for day in ledger.covered}


def test_a_day_after_a_long_gap_is_unknown_not_quiet():
    points = [(24 * HOUR, 1000, 30), (4 * DAY + 6 * HOUR, 1500, 40), (7 * DAY + 6 * HOUR, 1600, 55),
              (8 * DAY + 6 * HOUR, 1600, 55)]
    ledger = build_ledger(_series(points))
    # Между 05.09 18:00 и 08.09 18:00 замеров нет: прирост +15 мог прийти в
    # любые из этих суток, поэтому 06–08.09 неизвестны, а не «тихие».
    assert ledger.covered == ()
    assert ledger.growth == {}
    assert ledger.late == (100, 15)


def test_payload_round_trip_and_unknown_versions():
    points = [(24 * HOUR, 1000, 30), *_daily(4 * DAY + 6 * HOUR, 5, 1500, 40, 10, 2)]
    ledger = build_ledger(_series(points))
    again = ledger_from_payload(ledger.payload())
    assert again.payload() == ledger.payload()
    assert ledger_from_payload({"v": 99}) is None and ledger_from_payload(None) is None


def _detect(subject):
    prepared = prepare(subject, subject.observed_at[-1], CollectionCadence())
    return late_engagement.detect(prepared, DetectorContext(subject.platform))


def test_late_reactions_far_above_the_early_share_are_a_medium_sign():
    points = [(24 * HOUR, 2000, 40), *_daily(3.5 * DAY, 10, 2400, 45, 5, 6)]
    [sign] = _detect(_series(points))
    assert sign.pattern == 13 and sign.metric is Metric.REACTIONS
    assert late_engagement.MIN_STRENGTH <= sign.strength <= late_engagement.MAX_STRENGTH
    assert sign.render["kind"] == "late_engagement" and sign.render["ratio"] > 10
    assert "+54 реакций на +45 просмотров" in sign.formula


def test_ordinary_late_readers_or_a_couple_of_reactions_are_not_a_sign():
    # Поздняя доля ниже ранней — обычное старение внимания.
    assert _detect(_series([(24 * HOUR, 2000, 40), *_daily(3.5 * DAY, 10, 2400, 45, 200, 2)])) == ()
    # Девять поздних реакций — это один-два читателя, не картина.
    assert _detect(_series([(24 * HOUR, 2000, 40), *_daily(3.5 * DAY, 10, 2400, 45, 1, 1)])) == ()
    # Без ранней точки сравнивать не с чем.
    assert _detect(_series(_daily(3.5 * DAY, 10, 2400, 45, 5, 6))) == ()


def test_the_sign_is_kept_across_collection_gaps_and_stays_below_strong():
    case = synthetic_cases()["p13_late_engagement_max"]
    verdict = assess(case.subject)
    [sign] = [item for item in verdict.signs if item.pattern == 13]
    assert sign.strength < 0.7
    points = [(24 * HOUR, 2000, 40), (3.5 * DAY, 2400, 45), (9 * DAY, 2430, 100), (10 * DAY, 2440, 110)]
    assert 13 in {item.pattern for item in assess(_series(points)).signs}


def test_telegram_rounded_counters_are_accepted_with_a_mark_and_never_become_a_post_sign():
    points = [(24 * HOUR, 2000, 40), *_daily(3.5 * DAY, 10, 2400, 45, 5, 6)]
    rounded = {Metric.VIEWS: ("rounded",) * len(points), Metric.REACTIONS: ("rounded",) * len(points)}
    ledger = build_ledger(_series(points, platform="telegram", qualities=rounded))
    assert ledger.rounded and ledger.late == (45, 54) and ledger.payload()["rounded"] is True
    assert _detect(_series(points, platform="telegram", qualities=rounded)) == ()
    # Точные счётчики Telegram — обычный признак.
    assert _detect(_series(points, platform="telegram"))
    # Неизвестная точность и округление на других площадках не используются.
    unknown = {Metric.VIEWS: ("unknown",) * len(points), Metric.REACTIONS: ("unknown",) * len(points)}
    assert build_ledger(_series(points, platform="telegram", qualities=unknown)).late is None
    assert build_ledger(_series(points, platform="max", qualities=rounded)).late is None


def test_hourly_late_growth_goes_to_the_utc_hour_of_the_later_reading():
    # Публикация в 09:00 UTC; поздние замеры через полчаса: 33:00 → 10:00 UTC
    # следующих суток. Пары дальше часа, до суток и с уменьшением не считаются.
    points = [(2 * HOUR, 100, 5), (23.5 * HOUR, 900, 30), (24.5 * HOUR, 1000, 32),
              (25 * HOUR, 1010, 35), (25.5 * HOUR, 1030, 34), (28 * HOUR, 1100, 50),
              (28.5 * HOUR, 1105, 53)]
    ledger = build_ledger(_series(points))
    views, reactions = ledger.hours
    assert len(views) == len(reactions) == 24
    # 24,5 → 25 ч: 10:00 UTC (+10 просмотров, +3 реакции); 25 → 25,5 ч: 10:30
    # UTC (+20, реакции упали — 0); 28 → 28,5 ч: 13:30 UTC (+5, +3).
    assert views[10] == 30 and reactions[10] == 3
    assert views[13] == 5 and reactions[13] == 3
    # 23,5 → 24,5 ч — более поздний замер старше суток, но более ранний нет:
    # пара не целиком в позднем окне и не считается; 25,5 → 28 ч — разрыв > 1 ч.
    assert sum(views) == 35 and sum(reactions) == 6


def test_hourly_layout_skips_inexact_readings_and_reposts():
    # Округлённый замер выпадает из ряда, и его соседи дальше часа друг от друга.
    points = [(25 * HOUR, 1000, 30), (25.75 * HOUR, 1100, 40), (26.5 * HOUR, 1200, 50)]
    rounded = ("exact", "rounded", "exact")
    ledger = build_ledger(_series(points, qualities={Metric.VIEWS: rounded, Metric.REACTIONS: ("exact",) * 3}))
    assert ledger.hours is None
    assert build_ledger(_series(points, repost=True)).hours is None


def test_version_three_ledgers_are_still_readable_without_hours():
    points = [(24 * HOUR, 1000, 30), *_daily(4 * DAY + 6 * HOUR, 5, 1500, 40, 10, 2)]
    payload = {**build_ledger(_series(points)).payload(), "v": 3}
    payload.pop("hours", None)
    old = ledger_from_payload(payload)
    assert old is not None and old.hours is None and old.early.views == 1000
    assert build_ledger(_series(points)).payload()["v"] == 4
