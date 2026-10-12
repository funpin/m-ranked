"""Пакеты и подача просмотров: короткая с публикации, поздняя сквозь «1.2K»."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from anomaly_analysis.v2.detectors import DetectorContext, linear_feed
from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.series import CollectionCadence, prepare

MSK_NOON = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)   # 12:00 МСК


def tg_display(value: int) -> int:
    """Как Telegram показывает просмотры: три значащие цифры с тысячи."""
    if value < 1000:
        return value
    unit = 10 ** (len(str(value)) - 3)
    return value // unit * unit


def build(platform, rates, *, start=MSK_NOON, step=5, reactions=None, kind="photo", rounded=False,
          per_view=None):
    """Ряд по почасовым темпам просмотров; замер каждые `step` минут."""
    at, views, total = [], [], 0.0
    for minute in range(step, 60 * len(rates) + 1, step):
        total += rates[(minute - 1) // 60] * step / 60
        at.append(start + timedelta(minutes=minute))
        views.append(int(total))
    shown = [tg_display(value) for value in views] if rounded else views
    quality = tuple("rounded" if rounded and value >= 1000 else "exact" for value in views)
    reacts = (reactions if reactions is not None else
              [int(v * per_view) for v in views] if per_view is not None else
              [min(40 + i // 6, 400) for i in range(len(views))])
    return PostSeries(UUID(int=7), UUID(int=8), platform, start, False, tuple(at),
                      {Metric.VIEWS: tuple(shown), Metric.REACTIONS: tuple(reacts[:len(views)])},
                      qualities={Metric.VIEWS: quality, Metric.REACTIONS: ("exact",) * len(views)},
                      publication_type=kind)


def feed_signs(series):
    prepared = prepare(series, series.observed_at[-1], CollectionCadence())
    return [sign for sign in linear_feed.detect(prepared, DetectorContext(series.platform))
            if sign.metric is Metric.VIEWS]


def test_telegram_drip_through_rounded_views_is_found():
    # МИСИС 01.10: ~300/ч к шестому часу, затем ровно 1 200/ч ещё 30 часов
    # (ступенька вверх в 4 раза; конец ряда — подача ещё идёт).
    rates = [600, 400, 320, 300, 300, 300] + [1200] * 30
    signs = [s for s in feed_signs(build("telegram", rates, step=15, rounded=True))
             if s.render.get("mode") != "short_views"]
    assert signs and all(s.render["measurementMode"] == "bounded_views" for s in signs)


def test_organic_decay_through_rounding_is_not_a_feed():
    # Крупный пост: 3 000 → 300/ч плавно; «13.2K» и т. п. — без ступеньки и обрыва.
    rates = [3000, 2500, 2000, 1500, 1200, 1000, 800] + [300] * 10
    assert feed_signs(build("telegram", rates, step=15, rounded=True)) == []


def short(series):
    return [s for s in feed_signs(series) if s.render.get("mode") == "short_views"]


def kosygin(start=MSK_NOON, platform="vk", reactions=None, rounded=False, after=15, per_view=None):
    # ~400/ч три часа с публикации, затем `after`/ч: пакет ~1 200 при органике в десятки.
    return build(platform, [420, 400, 380] + [after] * 21, start=start, reactions=reactions,
                 rounded=rounded, per_view=per_view)


def pack_then_rest(pack_reactions, rest_reactions):
    """Реакции: `pack_reactions` за первые 3 ч, затем ровно до `rest_reactions` сверху."""
    return [round(pack_reactions * min(i, 36) / 36) + round(rest_reactions * max(0, i - 36) / 252)
            for i in range(288)]


def test_view_pack_from_publication_is_pronounced():
    # Обрыв в 6,7 раза (60/ч после), в пакете 2,5 реакции на 1 000, у остального поста ~24.
    (sign,) = short(kosygin(after=60, reactions=pack_then_rest(3, 30)))
    assert 0.75 <= sign.strength < 0.95
    assert 1000 <= sign.render["packViews"] <= 1300


def test_silent_pack_with_hard_stop_is_explicit():
    # Обрыв в 26 раз, в пакете ни одной реакции, остальной пост отвечает как обычно.
    (sign,) = short(kosygin(reactions=pack_then_rest(0, 30)))
    assert sign.strength >= 0.95


def test_pack_without_reactions_to_compare_stays_weak():
    # Реакций на посте нет вовсе: отклик не проверить — только слабый сигнал.
    (sign,) = short(kosygin(reactions=[0] * 288))
    assert sign.strength < 0.7


def test_organic_decay_is_not_a_pack():
    # Живой пост ВК: 400 → 200 → 120 → 80 … — без ровного участка и обрыва.
    assert short(build("vk", [400, 200, 120, 80, 60, 50, 40, 30, 25, 20] + [15] * 14)) == []


def test_pack_with_ordinary_response_is_not_flagged():
    # Попадание в рекомендации: темп ровный, но реакции идут как у остального поста.
    # После пакета 60/ч: у остального поста хватает реакций для сравнения.
    (sign,) = short(kosygin(after=60, per_view=0.012))
    assert sign.strength < 0.7 and "recommendation_feed" in sign.alternatives


def test_stop_at_night_is_not_evidence():
    late = datetime(2026, 10, 1, 18, tzinfo=timezone.utc)   # 21:00 МСК, обрыв ~00:00
    assert short(kosygin(start=late, reactions=pack_then_rest(0, 30))) == []


def test_vk_feed_limit_is_not_a_stop():
    # Ровные 400/ч с 12-го по 22-й час и спад на 22-м: это граница ленты ВК (22–26 ч).
    # Короткая ветка проверяется напрямую: поздняя ветка того же участка сильнее
    # и при сборке вытесняет короткий признак.
    series = build("vk", [60] * 12 + [400] * 10 + [5] * 6, reactions=pack_then_rest(0, 30) + [30] * 48)
    assert linear_feed._short_views(prepare(series, series.observed_at[-1], CollectionCadence())) is None


def test_collection_gap_inside_the_pack_gives_no_sign():
    series = kosygin(reactions=pack_then_rest(0, 30))
    keep = [i for i, at in enumerate(series.observed_at)
            if not timedelta(hours=1) <= at - series.published_at <= timedelta(hours=2, minutes=30)]
    gapped = PostSeries(series.publication_id, series.account_id, series.platform, series.published_at, False,
                        tuple(series.observed_at[i] for i in keep),
                        {m: tuple(col[i] for i in keep) for m, col in series.values.items()},
                        qualities={m: tuple(col[i] for i in keep) for m, col in series.qualities.items()},
                        publication_type="photo")
    assert short(gapped) == []


def test_rounded_telegram_pack_is_found_through_bounds():
    (sign,) = short(build("telegram", [1500, 1450, 1500] + [30] * 21, rounded=True,
                          reactions=pack_then_rest(1, 30)))
    assert sign.render["measurementMode"] == "bounded_views"
