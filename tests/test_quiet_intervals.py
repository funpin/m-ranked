"""Промежуток без замеров: равные края — плато, малый прирост — только границы темпа.

Клип КБГУ в ВК (№115600, 24.09.2026). До 07.10 сборщик хранил только
изменения: замеры шли, когда просмотры прибавляли 1–2, через полчаса–четыре
часа. На вторые сутки — пакет 154 → 4 620 просмотров за 3,3 ч при стоящих
лайках, затем снова +1–2 за часы. Такие промежутки были пробелами, и у пакета
не было ни фона, ни плато. Интерполяция же сквозь них рисовала бы ровный темп,
которого не было: на слепых карточках 13.10 это давало ложные «поздний
скачок» и «линейную подачу». Поэтому они дают только верхнюю и нижнюю
границу темпа — для фона, хвоста и тела рывка.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import numpy as np

from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.levels import assess
from anomaly_analysis.v2.series import CollectionCadence, prepare

PUBLISHED = datetime(2026, 9, 24, 7, 43, 22, tzinfo=timezone.utc)
# (возраст в часах, просмотры записи, лайки) — настоящие замеры первых 40 часов.
POINTS = (
    (0.02, 3, 0), (0.11, 5, 0), (0.19, 7, 0), (0.27, 8, 0), (0.36, 9, 0), (0.44, 11, 0), (0.52, 12, 0),
    (0.77, 13, 0), (0.94, 14, 0), (1.02, 17, 0), (1.11, 18, 0), (1.19, 19, 0), (1.44, 20, 0), (1.52, 21, 0),
    (2.27, 22, 0), (2.86, 23, 0), (3.11, 24, 0), (3.19, 34, 2), (3.27, 35, 2), (3.44, 37, 2), (3.61, 39, 2),
    (3.69, 40, 2), (4.02, 41, 2), (4.19, 43, 2), (4.86, 44, 2), (5.11, 49, 3), (5.19, 52, 3), (5.27, 53, 3),
    (5.52, 54, 3), (5.69, 56, 3), (5.86, 58, 3), (6.02, 62, 3), (6.37, 64, 3), (6.44, 72, 4), (6.52, 73, 4),
    (6.69, 74, 4), (6.77, 78, 5), (6.86, 79, 5), (6.94, 80, 5), (7.11, 81, 5), (7.19, 84, 5), (7.61, 85, 5),
    (7.77, 86, 5), (7.86, 88, 5), (7.94, 90, 5), (8.03, 91, 5), (8.19, 92, 5), (8.36, 97, 5), (8.69, 98, 5),
    (8.77, 99, 5), (8.86, 100, 5), (9.02, 102, 5), (9.11, 104, 6), (9.27, 105, 6), (9.52, 106, 6),
    (9.86, 108, 6), (9.94, 112, 6), (10.02, 113, 6), (10.19, 114, 6), (10.27, 115, 6), (10.36, 116, 6),
    (10.69, 117, 6), (10.78, 118, 6), (11.11, 120, 6), (11.27, 122, 6), (11.44, 123, 6), (11.86, 124, 6),
    (12.19, 125, 6), (12.44, 126, 6), (12.61, 129, 6), (12.94, 130, 6), (13.27, 131, 6), (13.94, 132, 6),
    (14.02, 133, 6), (14.77, 134, 6), (14.86, 137, 7), (15.02, 138, 7), (15.11, 139, 7), (15.52, 140, 7),
    (16.02, 141, 7), (19.69, 143, 7), (20.52, 144, 7), (20.86, 145, 7), (21.36, 146, 7), (21.44, 147, 7),
    (21.86, 149, 8), (22.03, 150, 8), (22.44, 151, 8), (22.52, 154, 8), (22.61, 256, 8), (22.69, 374, 8),
    (22.77, 495, 8), (22.86, 615, 9), (22.94, 726, 9), (23.02, 843, 9), (23.11, 956, 9), (23.19, 1073, 9),
    (23.27, 1198, 9), (23.36, 1299, 9), (23.44, 1409, 9), (23.52, 1520, 9), (23.61, 1640, 9), (23.69, 1766, 9),
    (23.77, 1877, 9), (23.86, 1991, 9), (23.94, 2098, 9), (24.02, 2208, 9), (24.27, 2555, 9), (24.52, 2885, 9),
    (24.77, 3201, 9), (25.02, 3552, 9), (25.27, 3877, 9), (25.52, 4209, 9), (25.77, 4549, 9), (25.86, 4620, 9),
    (28.02, 4622, 9), (28.77, 4623, 9), (29.02, 4625, 9), (29.69, 4626, 9), (30.11, 4627, 9), (30.52, 4632, 9),
    (31.02, 4634, 9), (31.11, 4635, 9), (31.61, 4636, 9), (31.94, 4637, 9), (32.44, 4638, 9), (33.86, 4640, 9),
    (35.36, 4641, 9), (36.11, 4644, 10), (36.69, 4645, 10), (37.02, 4649, 10), (37.27, 4654, 10),
)


def _series(points=POINTS) -> PostSeries:
    return PostSeries(uuid4(), uuid4(), "vk", PUBLISHED, False,
                      tuple(PUBLISHED + timedelta(hours=age) for age, _, _ in points),
                      {Metric.VIEWS: tuple(v for _, v, _ in points), Metric.REACTIONS: tuple(r for _, _, r in points)},
                      qualities={Metric.VIEWS: ("exact",) * len(points), Metric.REACTIONS: ("exact",) * len(points)},
                      interval_uncertain=(False,) * len(points), publication_type="video")


def _verdict(points=POINTS):
    series = _series(points)
    return assess(series, analyzed_at=series.observed_at[-1], cadence=CollectionCadence())


def test_view_pack_between_quiet_intervals_is_a_burst() -> None:
    verdict = _verdict()
    bursts = [sign for sign in verdict.signs if sign.pattern == 9 and sign.metric is Metric.VIEWS]
    assert bursts and int(verdict.level) >= 2
    start, end = ((moment - PUBLISHED).total_seconds() / 3600 for moment in (bursts[0].interval.start,
                                                                            bursts[0].interval.end))
    assert 21 <= start <= 23 and 25 <= end <= 27


def test_small_growth_stays_a_gap_with_bounds() -> None:
    series = _series()
    views = prepare(series, series.observed_at[-1], CollectionCadence()).metrics[Metric.VIEWS]
    # 16,0–19,7 ч: +2 просмотра за 3,7 ч — форма внутри неизвестна.
    assert [gap for gap in views.gaps if gap.start_age <= 17 * 3600 and gap.end_age >= 19 * 3600]
    grid = views.grids[timedelta(hours=1)]
    cell = int(np.searchsorted(grid.edges, 17 * 3600))
    assert not grid.usable[cell]
    assert 0 <= grid.quiet_lower[cell] <= grid.quiet_upper[cell] <= 3 / 3600


def test_equal_edges_are_a_plateau_not_a_gap() -> None:
    series = _series()
    reactions = prepare(series, series.observed_at[-1], CollectionCadence()).metrics[Metric.REACTIONS]
    # Лайки 9 → 9 с 23-го по 36-й час: пробелов нет.
    assert not [gap for gap in reactions.gaps if gap.start_age >= 23 * 3600 and gap.end_age <= 36 * 3600]


def test_interpolation_through_small_growth_draws_no_shape() -> None:
    """Без пакета тот же ряд остаётся без признаков: тихие промежутки не дают
    ни поздний скачок, ни линейную подачу."""
    quiet = tuple((age, v if age < 22.5 else v - 4466 if age > 25.9 else 154 + int(age), r)
                  for age, v, r in POINTS)
    quiet = tuple((age, max(v, quiet[i - 1][1]) if i else v, r) for i, (age, v, r) in enumerate(quiet))
    assert not [sign for sign in _verdict(quiet).signs if sign.metric is Metric.VIEWS and sign.pattern in (1, 2, 9)]
