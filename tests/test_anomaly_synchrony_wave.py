"""Медленная синхронная волна (признак 8, режим synchrony_wave).

Московский Политех в MAX 06.10: 28 постов возрастом до девяти суток несколько
часов подряд ровно набирали по 2–4 реакции в час, реакций к просмотрам — 26 %
при обычных 1–2 %. Ни один час не проходил порог подъёма, признак не ставился.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from anomaly_analysis.v2.detectors import DetectorContext, SiblingActivity, synchronous_rise
from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.series import HOUR, CollectionCadence, prepare

ACCOUNT = UUID("00000000-0000-4000-8000-00000000a003")
START = datetime(2026, 10, 4, 0, 0, tzinfo=timezone.utc)
PUBLISHED = START - timedelta(days=3)
HOURS = 60
WAVE = range(36, 46)          # десять часов волны
SIBLINGS = 12


def _rate(hour: int, wave_rate: int) -> tuple[int, int]:
    """Прирост реакций и просмотров за час: хвост почти стоит, в волне — капает."""
    if hour in WAVE:
        return wave_rate, 10 if wave_rate <= 3 else 30 * wave_rate
    return (1 if hour % 4 == 0 else 0), 40


def _levels(wave_rate: int) -> tuple[list[int], list[int]]:
    reactions, views, r, v = [], [], 100, 4000
    for hour in range(-1, HOURS + 1):
        dr, dv = _rate(hour, wave_rate)
        r, v = r + dr, v + dv
        reactions.append(r)
        views.append(v)
    return reactions, views


def _subject(wave_rate: int) -> PostSeries:
    reactions, views = _levels(wave_rate)
    instants = tuple(START + timedelta(hours=hour) for hour in range(-1, HOURS + 1))
    return PostSeries(UUID(int=1), ACCOUNT, "max", PUBLISHED, False, instants,
                      {Metric.VIEWS: tuple(views), Metric.REACTIONS: tuple(reactions)})


def _activity(wave_rate: int, siblings: int = SIBLINGS) -> SiblingActivity:
    first = int(START.timestamp() // HOUR)
    reactions, views = _levels(wave_rate)
    rows = [{"publication_id": UUID(int=10 + sibling), "published_at": PUBLISHED, "hour": first + index - 1,
             "reactions": reactions[index], "views": views[index]}
            for sibling in range(siblings) for index in range(HOURS + 2)]
    activity = SiblingActivity.from_hourly(rows, first, first + HOURS)
    assert activity is not None
    return activity


def _waves(wave_rate: int, siblings: int = SIBLINGS) -> list[dict]:
    prepared = prepare(_subject(wave_rate), START + timedelta(hours=HOURS), CollectionCadence())
    context = DetectorContext("max", None, _activity(wave_rate, siblings))
    return [dict(sign.render) for sign in synchronous_rise.detect(prepared, context)
            if sign.render.get("kind") == "synchrony_wave"]


def test_a_slow_drip_on_many_old_posts_is_a_synchronous_wave():
    waves = _waves(wave_rate=3)
    assert len(waves) == 1
    assert waves[0]["posts"] == SIBLINGS + 1
    # Окно в шесть часов отмечается, как только сумма перешла порог: его начало —
    # рядом с первым часом капели, не позже него.
    started = datetime.fromisoformat(waves[0]["hour"])
    assert START + timedelta(hours=WAVE.start - synchronous_rise.WAVE_HOURS) <= started <= START + timedelta(hours=WAVE.start)


def test_no_hourly_rise_is_reported_for_the_same_drip():
    prepared = prepare(_subject(3), START + timedelta(hours=HOURS), CollectionCadence())
    signs = synchronous_rise.detect(prepared, DetectorContext("max", None, _activity(3)))
    assert all(sign.render.get("kind") == "synchrony_wave" for sign in signs)


def test_a_wave_on_few_posts_is_not_enough():
    assert _waves(wave_rate=3, siblings=synchronous_rise.WAVE_MIN_SIBLINGS - 1) == []


def test_reactions_that_follow_views_are_an_external_push_not_a_wave():
    # Тридцать просмотров на реакцию — та же доля, что вне волны.
    assert _waves(wave_rate=4) == []


# Молодой пост внутри волны: Московский Политех в MAX, 06.10 — посты,
# опубликованные в часы волны, набрали по 100–120 реакций на ~1 000 просмотров
# (обычно 10–25) и признака не получали: сравнивать их с собственным хвостом
# нельзя, хвоста ещё нет.
YOUNG_PUBLISHED = START + timedelta(hours=WAVE.start - 1)
FRESH = (2, 8)                 # свежие посты до волны: опубликованы на 2-м и 8-м часу


def _fresh_rows(first: int) -> list[dict]:
    """Свежие посты до волны: в первые сутки 2 реакции на 100 просмотров в час."""
    rows = []
    for number, published_hour in enumerate(FRESH):
        r = v = 0
        for hour in range(published_hour, HOURS + 1):
            r, v = r + (2 if hour - published_hour < 24 else 0), v + (100 if hour - published_hour < 24 else 5)
            rows.append({"publication_id": UUID(int=100 + number), "published_at": START + timedelta(hours=published_hour),
                         "hour": first + hour, "reactions": r, "views": v})
    return rows


def _young(reactions_per_hour: int, views_per_hour: int) -> PostSeries:
    instants, reactions, views, r, v = [], [], [], 0, 0
    for minutes in range(5, (HOURS - WAVE.start + 1) * 60, 15):
        at = YOUNG_PUBLISHED + timedelta(minutes=minutes)
        r, v = r + reactions_per_hour / 4, v + views_per_hour / 4
        instants.append(at)
        reactions.append(int(r))
        views.append(int(v))
    return PostSeries(UUID(int=2), ACCOUNT, "max", YOUNG_PUBLISHED, False, tuple(instants),
                      {Metric.VIEWS: tuple(views), Metric.REACTIONS: tuple(reactions)})


def _young_waves(subject: PostSeries, fresh: bool = True) -> list:
    first = int(START.timestamp() // HOUR)
    reactions, views = _levels(3)
    rows = [{"publication_id": UUID(int=10 + sibling), "published_at": PUBLISHED, "hour": first + index - 1,
             "reactions": reactions[index], "views": views[index]}
            for sibling in range(SIBLINGS) for index in range(HOURS + 2)]
    activity = SiblingActivity.from_hourly(rows + (_fresh_rows(first) if fresh else []), first, first + HOURS)
    prepared = prepare(subject, START + timedelta(hours=HOURS), CollectionCadence())
    return [sign for sign in synchronous_rise.detect(prepared, DetectorContext("max", None, activity))
            if sign.render.get("kind") == "synchrony_wave"]


def test_a_post_born_inside_a_wave_is_its_member():
    # 6 реакций на 40 просмотров в час — 15 % при 2 % у свежих постов до волны.
    signs = _young_waves(_young(6, 40))
    # Волна в десять часов — до двух шестичасовых окон; в выводе они одно событие.
    assert 1 <= len(signs) <= 2 and all(item.render["member"] == "young" for item in signs)
    sign = signs[0]
    assert sign.render["posts"] == SIBLINGS + 1
    assert sign.strength == synchronous_rise.YOUNG_MAX_STRENGTH
    assert sign.interval.start >= YOUNG_PUBLISHED
    assert "свежие посты аккаунта до волны" in sign.formula


def test_a_fresh_post_with_the_usual_share_is_not_a_member():
    # Те же 2 % — обычный свежий пост, опубликованный во время чужой волны.
    assert _young_waves(_young(2, 100)) == []


def test_no_member_without_fresh_posts_to_compare_with():
    assert _young_waves(_young(6, 40), fresh=False) == []
