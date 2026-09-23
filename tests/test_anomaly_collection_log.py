"""Журнал циклов сбора: «не менялось» против «нет данных» и то, что это открыло детекторам.

Сборщик пишет замер поста, только когда значения изменились. Без журнала
плато после рывка выглядело пробелом, и рывок не судился; синхронный вброс
через час после простоя не находился; ночная тишина делала из утреннего
оживления «подачу».
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import numpy as np

from anomaly_analysis.v2.detectors import DetectorContext, SiblingActivity, burst_plateau, linear_feed, synchronous_rise
from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.schedule import ScheduleConfig
from anomaly_analysis.v2.series import HOUR, MINUTE, CollectionCadence, confirm_unchanged, prepare

PUBLISHED = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)   # 12:00 МСК
ACCOUNT = UUID("00000000-0000-4000-8000-00000000a001")


def series(points, *, collected=(), platform="max", publication=1) -> PostSeries:
    """points — (минуты от публикации, просмотры, реакции)."""
    return PostSeries(
        UUID(int=publication), ACCOUNT, platform, PUBLISHED, False,
        tuple(PUBLISHED + timedelta(minutes=minute) for minute, _, _ in points),
        {Metric.VIEWS: tuple(views for _, views, _ in points),
         Metric.REACTIONS: tuple(reactions for _, _, reactions in points)},
        tuple(PUBLISHED + timedelta(minutes=minute) for minute in collected))


def every(start_minutes: float, stop_minutes: float, step_minutes: float) -> list[float]:
    return [float(item) for item in np.arange(start_minutes, stop_minutes, step_minutes)]


def test_quiet_stretch_with_collection_is_confirmed_and_an_outage_stays_a_gap():
    cadence = CollectionCadence()
    ages = np.array([0, 300, 600, 20 * HOUR, 20 * HOUR + 300, 30 * HOUR], dtype=float)
    runs = np.concatenate([np.arange(300, 20 * HOUR, 300), np.arange(20 * HOUR + 300, 24 * HOUR, 900)])
    out, rows, covered = confirm_unchanged(ages, runs.astype(float), cadence, "telegram")
    # Перенесённая точка за шаг до последнего цикла перед новым замером.
    assert rows.tolist() == [0, 1, 2, 2, 3, 4, 4, 5]
    assert out[3] == 20 * HOUR - 300 - 300
    # Всё до 24 ч подтверждено; последние шесть часов циклов не было — пробел.
    assert covered.tolist() == [False, True, True, True, True, True, True, False]


def test_without_a_collection_log_nothing_changes():
    ages = np.array([0, 300, 20 * HOUR], dtype=float)
    out, rows, covered = confirm_unchanged(ages, np.zeros(0), CollectionCadence(), "vk")
    assert out.tolist() == ages.tolist() and rows.tolist() == [0, 1, 2] and not covered.any()


def _jump_then_plateau(collected):
    # Просмотры тикают каждые 5 минут первые сутки; реакции стоят на 5, в
    # 20:00 скачок до 40 и дальше ни одного нового замера — плато.
    points = [(minute, 100 + int(minute // 5), 5) for minute in every(0, 20 * 60, 5)]
    points += [(20 * 60 + 5, 340, 25), (20 * 60 + 10, 341, 40)]
    return series(points, collected=collected)


def test_jump_into_a_plateau_is_judged_when_collection_confirms_the_plateau():
    subject = _jump_then_plateau(every(5, 26 * 60, 5))
    prepared = prepare(subject, PUBLISHED + timedelta(hours=26), CollectionCadence())
    signs = burst_plateau.detect(prepared, DetectorContext("max"))
    assert any(sign.metric is Metric.REACTIONS and sign.strength >= 0.7 for sign in signs)


def test_the_same_plateau_without_a_collection_log_is_not_judged():
    subject = _jump_then_plateau(())
    prepared = prepare(subject, PUBLISHED + timedelta(hours=26), CollectionCadence())
    assert not [sign for sign in burst_plateau.detect(prepared, DetectorContext("max"))
                if sign.metric is Metric.REACTIONS]


def test_early_reaction_pack_detached_from_views_is_a_plateau_sign():
    # Telegram: за первые 15 минут 52 реакции на 79 просмотров, потом зрители
    # идут (до ~300), а реакций прибавляется три.
    points = [(0, 0, 0), (5, 40, 20), (10, 79, 52)]
    points += [(minute, 79 + int((minute - 10) * 1.1), 52 + int((minute - 10) // 70)) for minute in every(15, 4 * 60, 5)]
    subject = series(points, platform="telegram", collected=every(5, 4 * 60, 5))
    prepared = prepare(subject, PUBLISHED + timedelta(hours=4), CollectionCadence())
    signs = [sign for sign in burst_plateau.detect(prepared, DetectorContext("telegram"))
             if sign.metric is Metric.REACTIONS]
    assert signs and signs[0].render["mode"] == "early_plateau" and signs[0].strength >= 0.6


def test_organic_reactions_that_follow_views_are_not_an_early_plateau():
    # Реакции идут вместе с просмотрами — 6 % от прироста просмотров всё время.
    points = [(minute, int(400 * (1 - np.exp(-minute / 90))), int(24 * (1 - np.exp(-minute / 90))))
              for minute in every(0, 4 * 60, 5)]
    subject = series(points, platform="telegram", collected=every(5, 4 * 60, 5))
    prepared = prepare(subject, PUBLISHED + timedelta(hours=4), CollectionCadence())
    assert not burst_plateau.detect(prepared, DetectorContext("telegram"))


def test_hourly_activity_carries_quiet_hours_only_when_collection_ran():
    first = int(PUBLISHED.timestamp() // HOUR)
    rows = [{"publication_id": UUID(int=7), "published_at": PUBLISHED, "hour": first + hour,
             "reactions": value, "views": value * 10} for hour, value in ((0, 5), (4, 9))]
    carried = SiblingActivity.from_hourly(rows, first, first + 6, {first + hour for hour in range(6)})
    silent = SiblingActivity.from_hourly(rows, first, first + 6)
    # Прирост первого часа окна неизвестен: уровня часа до него нет.
    assert np.isnan(carried.reactions[0][0])
    assert carried.reactions[0].tolist()[1:5] == [0.0, 0.0, 0.0, 4.0]
    assert np.isnan(silent.reactions[0][:5]).all()


def test_synchronous_rise_an_hour_after_an_outage_is_found():
    """Вброс на семь постов через час после простоя сбора (Московский Политех, 02.09)."""
    resume = 30 * 60   # сбор возобновился на 30-м часу жизни первого поста
    rise_at = resume + 60

    def post(publication, offset_minutes, base, jump):
        points = [(minute, 1000 + int(minute // 60), base) for minute in every(resume - offset_minutes, rise_at - offset_minutes, 15)]
        points += [(minute, 1100 + int(minute // 60), base + jump)
                   for minute in every(rise_at - offset_minutes + 15, rise_at - offset_minutes + 6 * 60, 15)]
        return PostSeries(UUID(int=publication), ACCOUNT, "max", PUBLISHED + timedelta(minutes=offset_minutes), False,
                          tuple(PUBLISHED + timedelta(minutes=offset_minutes + minute) for minute, _, _ in points),
                          {Metric.VIEWS: tuple(v for _, v, _ in points), Metric.REACTIONS: tuple(r for _, _, r in points)},
                          tuple(PUBLISHED + timedelta(minutes=minute) for minute in every(resume, rise_at + 6 * 60, 5)))

    posts = [post(index + 1, index * 120, 10, 40 + 10 * index) for index in range(4)]
    start = (PUBLISHED + timedelta(minutes=resume - 60)).timestamp()
    end = (PUBLISHED + timedelta(minutes=rise_at + 6 * 60)).timestamp()
    subject, others = posts[0], posts[1:]
    activity = SiblingActivity.from_series(others, start, end)
    prepared = prepare(subject, PUBLISHED + timedelta(minutes=rise_at + 6 * 60), CollectionCadence())
    signs = synchronous_rise.detect(prepared, DetectorContext("max", None, activity))
    assert any(sign.metric is Metric.REACTIONS and sign.render["posts"] >= 3 for sign in signs)


def test_morning_revival_after_a_quiet_night_is_not_a_linear_feed():
    # Пост 18:00 МСК: вечер затухает, ночь 00–07 МСК почти тихая (сбор идёт),
    # с 07:00 ровный дневной приток — суточный ритм, а не подача.
    published = datetime(2026, 9, 20, 15, 0, tzinfo=timezone.utc)
    minutes, views = [], []
    value = 0.0
    for minute in every(0, 30 * 60, 15):
        clock = (published + timedelta(minutes=minute) + timedelta(hours=3)).hour
        rate = 600 / (1 + minute / 60) if clock >= 7 or minute < 6 * 60 else 2
        if 7 <= clock < 20 and minute > 12 * 60:
            rate = 120
        value += rate / 4
        minutes.append(minute), views.append(int(value))
    subject = PostSeries(UUID(int=9), ACCOUNT, "vk", published, False,
                         tuple(published + timedelta(minutes=minute) for minute in minutes),
                         {Metric.VIEWS: tuple(views)},
                         tuple(published + timedelta(minutes=minute) for minute in every(5, 30 * 60, 15)))
    prepared = prepare(subject, published + timedelta(hours=30), CollectionCadence())
    assert not linear_feed.detect(prepared, DetectorContext("vk"))


def test_every_post_the_site_shows_is_queued_for_analysis():
    config = ScheduleConfig()
    # Сайт показывает посты за 70 суток; окно постановки в очередь не уже.
    assert config.seed_seconds >= 70 * 24 * HOUR > config.track_seconds
    assert ScheduleConfig.from_environment({"ANOMALY_SEED_WINDOW_HOURS": "100"}).seed_seconds == config.track_seconds
    assert MINUTE == 60


def test_backfill_finds_old_synchrony_with_whole_window_activity(monkeypatch):
    """Разовая перепроверка: агрегаты аккаунта на всё окно, запись тем же путём."""
    import sys
    from anomaly_analysis import backfill
    from anomaly_analysis.v2.store import DueRow
    from anomaly_reference.mature_norms import synthetic_cases

    case = synthetic_cases()["p08_synchronous_rise_telegram"]
    subject = case.subject
    activity = SiblingActivity.from_series(case.siblings, subject.observed_at[0].timestamp() - 86400,
                                           subject.observed_at[-1].timestamp())
    written = []

    class Store:
        def __init__(self, dsn):
            pass

        def latest_accepted_norm_version(self):
            return None

        def backfill_accounts(self, since):
            return [subject.account_id]

        def backfill_targets(self, account, since):
            return [DueRow(subject.publication_id, subject.published_at, since, None, None, None, 0, ())]

        def read_activity(self, accounts, since, until, published_since):
            return {subject.account_id: activity}

        def read_subscribers(self, accounts, since, until):
            return {}

        def read_series(self, targets):
            return {subject.publication_id: subject}

        def write_states(self, writes):
            written.extend(writes)

    monkeypatch.setattr(backfill, "PostgresAnomalyStore", Store)
    monkeypatch.setenv("ANOMALY_DATABASE_URL", "postgresql://example.invalid/x")
    monkeypatch.setattr(sys, "argv", ["backfill", "--days", "35"])
    backfill.main()
    (write,) = written
    assert write.reason == "backfill" and write.verdict is not None
    assert any(sign.pattern == synchronous_rise.PATTERN for sign in write.verdict.signs)


def test_early_pack_before_the_first_grid_edge_is_found():
    """СКФУ №16769: 5 реакций на 2,5 минуте, 52 на 7,5 — раньше первой границы сетки."""
    points = [(2.5, 43, 5), (7.5, 79, 52)]
    points += [(minute, 79 + int((minute - 7.5) * 1.3), 52 + int((minute - 7.5) // 90))
               for minute in every(12.5, 4 * 60, 5)]
    subject = series(points, platform="telegram", collected=every(2.5, 4 * 60, 5))
    prepared = prepare(subject, PUBLISHED + timedelta(hours=4), CollectionCadence())
    signs = [sign for sign in burst_plateau.detect(prepared, DetectorContext("telegram"))
             if sign.metric is Metric.REACTIONS]
    assert signs and signs[0].render["mode"] == "early_plateau"
    assert signs[0].interval.start == PUBLISHED
