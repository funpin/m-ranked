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
