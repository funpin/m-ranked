"""Посты из разбора владельца 07.10.2026: что раньше не помечалось и почему теперь помечается."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from reported_cases import CASES, reported
from anomaly_analysis.v2.detectors import DetectorContext, engagement_regime, joint_cliff, reaction_write_off
from anomaly_analysis.v2.domain import Level, Metric
from anomaly_analysis.v2.levels import assess, compact
from anomaly_analysis.v2.series import CollectionCadence, prepare

R, V = Metric.REACTIONS, Metric.VIEWS
HOUR = 3600


def hours(series, sign):
    return ((sign.interval.start - series.published_at).total_seconds() / HOUR,
            (sign.interval.end - series.published_at).total_seconds() / HOUR)


def detect(detector, series):
    return detector.detect(prepare(series, series.observed_at[-1], CollectionCadence()),
                           DetectorContext(series.platform))


@pytest.mark.parametrize("name, start, end", [
    # Реакции ~54/ч с 3,6 до 8,8 ч, затем сутки без единой реакции.
    ("02_linear_pack_then_stop", 3, 9.5),
    # 0 → 119 реакций за три часа, затем +1 на 1 900 просмотров.
    ("03_early_pack_then_stop", 0.3, 3.2),
    # Репост: +37 реакций при +8 просмотрах за 15 минут.
    ("04_repost_instant_step", 3.4, 4.5),
    # Сутки без реакций, затем +19 на 162 просмотра.
    ("10_late_start", 23, 34),
    # ~1 000 реакций ровно с 1-го по 18-й час, затем остановка.
    ("14_long_linear_pack", 0.5, 18.5),
])
def test_reaction_packs_reach_the_highest_level_with_the_whole_episode(name, start, end):
    series = reported(name)
    verdict = assess(series)
    assert verdict.level is Level.ARTIFICIAL_ACTIVITY_SIGNS
    (episode,) = [sign for sign in verdict.signs if sign.pattern == engagement_regime.PATTERN]
    begin, finish = hours(series, episode)
    assert start <= begin and finish <= end, (begin, finish)
    assert episode.render["plateauEvidence"] == engagement_regime.CONFIRMED_MODE


def test_repost_episode_uses_the_reposts_own_views():
    series = reported("04_repost_instant_step")
    assert series.is_repost
    payload = compact(assess(series))
    assert "repost_source_counter" not in payload["quality"]["codes"]
    assert not any("требу" in signal["title"] for signal in payload["signals"])


def test_joint_cliff_of_views_and_reactions_is_pronounced():
    series = reported("05_joint_cliff")
    verdict = assess(series)
    assert verdict.level >= Level.PRONOUNCED_ANOMALY
    (cliff,) = [sign for sign in verdict.signs if sign.pattern == joint_cliff.PATTERN]
    assert 6 <= hours(series, cliff)[1] <= 7


def test_write_off_is_pronounced_and_names_the_removed_reactions():
    series = reported("06_write_off")
    verdict = assess(series)
    assert verdict.level >= Level.PRONOUNCED_ANOMALY
    (write_off,) = [sign for sign in verdict.signs if sign.pattern == reaction_write_off.PATTERN]
    assert write_off.render["before"] == 111 and write_off.render["removed"] == 79


@pytest.mark.parametrize("name", [name for name in CASES if name.startswith("control_")])
def test_busy_organic_posts_stay_clean(name):
    series = reported(name)
    for detector in (engagement_regime, joint_cliff, reaction_write_off):
        assert detect(detector, series) == (), (name, detector.ID)


def test_restored_counter_is_a_glitch_not_a_write_off():
    series = reported("06_write_off")
    values = list(series.values[R])
    drop = next(index for index in range(1, len(values)) if values[index] < values[index - 1] - 50)
    # Значение вернулось следующим замером — сбой выдачи.
    values[drop] = values[drop - 1] - 79
    for index in range(drop + 1, len(values)):
        values[index] = max(values[index], values[drop - 1])
    assert detect(reaction_write_off, replace(series, values={**series.values, R: tuple(values)})) == ()


def test_evening_cliff_inside_moscow_night_is_not_a_sign():
    series = reported("05_joint_cliff")
    # Тот же ряд, сдвинутый так, что обрыв приходится на 01:00 по Москве.
    shift = timedelta(hours=7)
    moved = replace(series, published_at=series.published_at + shift,
                    observed_at=tuple(at + shift for at in series.observed_at))
    assert detect(joint_cliff, moved) == ()


def test_granular_counter_updates_are_not_mistaken_for_a_pack():
    # Каждое органическое событие ×10 (пакетное обновление счётчика): форма та
    # же, что у живого поста, — квазипуассоновский разброс гасит зернистость.
    series = reported("control_max_0")
    coarse = tuple(None if value is None else value * 10 for value in series.values[R])
    assert detect(engagement_regime, replace(series, values={**series.values, R: coarse})) == ()


def test_short_burst_highlights_the_whole_pack_it_belongs_to():
    # Рывок доказан на 15 минутах, но пакет — 0 → 64 реакции за первые ~2 часа.
    series = reported("09_pack_range")
    (burst,) = [sign for sign in assess(series).signs if sign.pattern == 9]
    begin, finish = hours(series, burst)
    assert begin < 0.5 and 1.5 < finish < 2.5
    assert burst.render["burstEndAge"] - burst.render["burstStartAge"] <= 30 * 60


def test_rutube_hour_long_wave_after_a_quiet_day_is_typical():
    # Видео RuTube смотрят по ссылке из соцсети: волна за час и тишина. По
    # журналу циклов так выглядят 13 % постов RuTube из 30 аккаунтов, поэтому
    # волна просмотров и реакции в ту же волну в вывод не идут.
    from datetime import datetime, timezone
    from uuid import UUID
    from anomaly_analysis.v2.domain import PostSeries
    published = datetime(2026, 9, 28, 14, 1, tzinfo=timezone.utc)
    ages = [0.25 + hour + 0.0001 * hour for hour in range(0, 30)]
    views = [20 + hour for hour in range(18)] + [1749 + hour for hour in range(12)]
    likes = [1] * 18 + [97] * 12
    series = PostSeries(UUID(int=99), UUID(int=98), "rutube", published, False,
                        tuple(published + timedelta(hours=age) for age in ages),
                        {V: tuple(views), R: tuple(likes)})
    assert assess(series).level is Level.NONE
    # Те же 97 лайков за час без волны просмотров — реакции, оторванные от аудитории.
    flat = PostSeries(UUID(int=99), UUID(int=98), "rutube", published, False, series.observed_at,
                      {V: tuple(20 + hour for hour in range(30)), R: tuple(likes)})
    assert assess(flat).level >= Level.PRONOUNCED_ANOMALY


def test_pack_collected_before_the_first_read_counts_from_publication():
    # ВК №149026 ГУАП: к пятой минуте 61 лайк на 73 просмотра, затем +7 лайков
    # на +1 400 просмотров за десять суток. Без нуля в момент публикации
    # эпизод начинался с уже набранного пакета и не находился.
    series = reported("11_vk_pack_before_first_read")
    (episode,) = detect(engagement_regime, series)
    assert episode.render["mode"] == "stop" and hours(series, episode)[0] == 0
    assert assess(series).level is Level.ARTIFICIAL_ACTIVITY_SIGNS


def test_hours_long_start_pack_on_a_small_post_is_left_to_the_account_finding():
    # ГУАП в MAX: ~57 реакций за 3,5 ч, затем +2 на ~220 просмотров за сутки.
    # Падение доли не меньше чем в 5 раз (99 %) — в пределах органического (до
    # 4–5 раз у 90 % постов); закономерность видна только на многих постах.
    series = reported("12_max_hours_long_start_pack")
    assert detect(engagement_regime, series) == ()
    from anomaly_analysis.v2.account_findings import pack_ratio
    from anomaly_analysis.v2.tail_ledger import build_ledger
    ratio, *_ = pack_ratio(build_ledger(series, series.observed_at[-1]))
    assert ratio >= 8


def test_rutube_history_uses_account_cycles_to_place_the_growth():
    # e6953fb9: 1 просмотр в 14:16, следующая сохранённая точка — через 18 ч
    # (1 749 просмотров, 97 лайков), между ними 18 успешных часовых циклов.
    # На RuTube цикл перечитывает каждый неизменившийся пост (квитанции:
    # 486 из 486), значит рост пришёл за последний час.
    from datetime import datetime, timezone
    from uuid import UUID
    from anomaly_analysis.v2.domain import PostSeries
    published = datetime(2026, 9, 28, 14, 1, 9, tzinfo=timezone.utc)
    points = [(0.25, 1, 0), (18.25, 1749, 97), (19.26, 1846, 97), (44.25, 1846, 97), (68.25, 1846, 97)]
    cycles = tuple(published + timedelta(hours=0.23 + hour) for hour in range(70))

    def series(platform, collected):
        return PostSeries(UUID(int=5), UUID(int=6), platform, published, False,
                          tuple(published + timedelta(hours=age) for age, *_ in points),
                          {V: tuple(item[1] for item in points), R: tuple(item[2] for item in points)}, collected)
    at = published + timedelta(hours=69)
    held = prepare(series("rutube", cycles), at, CollectionCadence()).metrics[V]
    # Перед ростом — точка в начале последнего цикла с прежним значением.
    assert [round(age / 3600, 2) for age in held.ages[:3]] == [0.25, 17.23, 18.25] and held.values[1] == 1
    # На других площадках цикл аккаунта чтения поста не доказывает.
    assert prepare(series("vk", cycles), at, CollectionCadence()).metrics[V].ages.size == len(points)
    # Сама волна для RuTube обычна (см. тест выше): вывода нет, но рост на графике
    # и в анализе стоит на своём часе.
    assert assess(series("rutube", cycles), analyzed_at=at).level is Level.NONE
