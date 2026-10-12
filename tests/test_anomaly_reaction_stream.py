"""Поток одной реакции (признак 17) и выборочное чтение состава реакций."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from anomaly_analysis.v2.detectors import DetectorContext, reaction_stream
from anomaly_analysis.v2.domain import Family, Level, Metric, PostSeries
from anomaly_analysis.v2.levels import assess, compact
from anomaly_analysis.v2.series import CollectionCadence, prepare
from anomaly_analysis.v2.store import KINDS_HOURS, needs_reaction_kinds, series_from_rows

PUBLISHED = datetime(2026, 10, 7, 8, 15, 13, tzinfo=timezone.utc)
MINUTE = 60


def telegram(points, platform="telegram", kinds=True):
    """points — (минуты от публикации, просмотры, состав реакций)."""
    observed = tuple(PUBLISHED + timedelta(minutes=minute) for minute, _, _ in points)
    views = tuple(view for _, view, _ in points)
    reactions = tuple(sum(mix.values()) for _, _, mix in points)
    return PostSeries(UUID(int=17), UUID(int=7), platform, PUBLISHED, False, observed,
                      {Metric.VIEWS: views, Metric.REACTIONS: reactions},
                      reaction_kinds=tuple(mix for _, _, mix in points) if kinds else ())


def permian_polytech():
    """Пермский Политех в Telegram, 07.10.2026: прочие реакции встали за первый час,
    «🙈» шла по ~5 за пять минут ещё два часа и оборвалась."""
    points, others, monkeys, views = [], 0, 0, 0
    for minute in range(3, 24 * 60, 5):
        if minute <= 60:
            others = min(38, others + 4)
            monkeys += 3
            views += 40
        elif minute <= 188:
            others += minute % 25 == 3
            monkeys += 5
            views += 15
        else:
            others += minute % 120 == 3
            monkeys += minute % 60 == 3
            views += 2
        points.append((minute, views, {"🙈": monkeys, "❤": others * 2 // 3, "🎉": others - others * 2 // 3}))
    return telegram(points)


def detect(series):
    return reaction_stream.detect(prepare(series, series.observed_at[-1], CollectionCadence()),
                                  DetectorContext(series.platform))


def test_one_reaction_running_apart_from_the_rest_is_a_pronounced_sign():
    (sign,) = detect(permian_polytech())
    assert sign.pattern == 17 and sign.family is Family.COMPOSITION and sign.metric is Metric.REACTIONS
    assert sign.strength == 0.75
    assert sign.render["reaction"] == "🙈" and sign.render["keyDelta"] >= 100
    start, end = ((moment - PUBLISHED).total_seconds() / 3600 for moment in (sign.interval.start, sign.interval.end))
    # Окно — где перекос невероятнее всего: от первого часа до конца ровного темпа и дальше,
    # пока «🙈» продолжает обгонять прочие.
    assert 0.5 <= start <= 1.5 and 3 <= end <= reaction_stream.MAX_SPAN / 3600 + 1.5, (start, end)
    assert "«🙈»" in sign.formula and "вне окна" in sign.formula


def test_the_stream_reaches_the_card_with_its_title():
    payload = compact(assess(permian_polytech()))
    # Ровные 5 за пять минут в синтетике видит и линейная подача: два семейства.
    assert payload["level"] >= Level.PRONOUNCED_ANOMALY
    (signal,) = [item for item in payload["signals"] if item["pattern"] == 17]
    assert signal["title"] == "Поток одной реакции" and signal["family"] == "composition"
    assert signal["render"]["kind"] == "stream"


def test_a_reaction_the_audience_prefers_all_along_is_not_a_stream():
    # Траурный пост: «🙏» — четыре из пяти реакций с первой минуты до конца суток.
    points, total = [], 0
    for minute in range(3, 24 * 60, 5):
        total += 6 if minute < 180 else (minute % 30 == 3)
        points.append((minute, total * 10, {"🙏": total * 4 // 5, "😢": total - total * 4 // 5}))
    assert detect(telegram(points)) == ()


def test_a_channel_with_one_allowed_reaction_has_no_stream():
    points = [(minute, minute * 5, {"👍": minute // 2}) for minute in range(3, 600, 5)]
    assert detect(telegram(points)) == ()


@pytest.mark.parametrize("change", ["other_platform", "no_kinds", "small"])
def test_no_stream_without_telegram_kinds_or_volume(change):
    series = permian_polytech()
    if change == "other_platform":
        series = telegram([(m, v, mix) for m, v, mix in _points(series)], platform="max")
    elif change == "no_kinds":
        series = telegram(_points(series), kinds=False)
    else:
        # Тот же рисунок, но в окне «🙈» меньше тридцати.
        series = telegram([(m, v, {**mix, "🙈": mix["🙈"] // 6}) for m, v, mix in _points(series)])
    assert detect(series) == ()


def test_paid_stars_are_not_viewer_reactions():
    points = [(m, v, {**mix, "paid:star": mix["🙈"]}) for m, v, mix in _points(permian_polytech())]
    (sign,) = detect(telegram(points))
    assert sign.render["reaction"] == "🙈"


def _points(series):
    return [(int((at - PUBLISHED).total_seconds() // MINUTE), view, dict(mix))
            for at, view, mix in zip(series.observed_at, series.values[Metric.VIEWS], series.reaction_kinds)]


def _rows(platform, reactions_by_minute):
    return [{"id": UUID(int=17), "primary_account_id": UUID(int=7), "platform": platform,
             "published_at": PUBLISHED, "is_repost": False, "observed_at": PUBLISHED + timedelta(minutes=minute),
             "interval_uncertain": False, "views_count": minute, "views_quality": "exact",
             "reactions_count": count, "reactions_quality": "exact", "comments_count": None,
             "comments_quality": "unknown", "shares_count": None, "shares_quality": "unknown",
             "reaction_breakdown": None} for minute, count in reactions_by_minute]


@pytest.mark.parametrize("platform,points,expected", [
    # +30 за первые 6 ч от нуля публикации — состав нужен.
    ("telegram", [(10, 12), (200, 31)], True),
    # +29 — потока не может быть.
    ("telegram", [(10, 12), (200, 29)], False),
    # Рост в 30 растянут на 7 ч: в окно шести часов не помещается.
    ("telegram", [(60, 0), (300, 15), (480, 30)], False),
    # Позже первых суток состав не читается.
    ("telegram", [(KINDS_HOURS * 60 + 10, 0), (KINDS_HOURS * 60 + 60, 80)], False),
    ("max", [(10, 12), (200, 90)], False),
])
def test_kinds_are_read_only_where_a_stream_is_possible(platform, points, expected):
    assert needs_reaction_kinds(_rows(platform, points)) is expected


def test_series_carries_kinds_by_observation_moment():
    rows = _rows("telegram", [(10, 3), (20, 5)])
    series = series_from_rows(rows, kinds={rows[1]["observed_at"]: {"❤": 5}})
    assert series.reaction_kinds == (None, {"❤": 5})
    assert series.reaction_breakdowns == (None, None)
    assert series_from_rows(rows).reaction_kinds == ()
