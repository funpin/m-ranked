"""Фон рывка реакций, когда замера ровно за шесть часов до него нет.

Клип МИФИ в ВК (№35481, 12.09.2026). До 07.10 сборщик хранил только
изменения, и между замерами на шестые сутки было по 3–6 часов. Лайки стояли
на 9 больше суток, затем +78 за полчаса и снова плато. Последний замер перед
рывком — за 5 ч 55 мин, предыдущий — за 8 ч 50 мин: окно фона «6 ч ± 1 ч»
не находило ни одного, и рывок отбрасывался.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from anomaly_analysis.v2.detectors import DetectorContext, bounded_reaction_burst
from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.series import CollectionCadence, prepare

PUBLISHED = datetime(2026, 9, 12, 6, 5, 54, tzinfo=timezone.utc)
# (возраст в часах, просмотры записи, лайки) — настоящие замеры первых 200 часов.
POINTS = (
    (0.07, 1, 0), (0.23, 196, 0), (0.39, 430, 0), (0.53, 636, 0), (0.68, 857, 1), (0.83, 1075, 1),
    (0.99, 1303, 1), (1.14, 1524, 1), (1.28, 1733, 1), (1.44, 1945, 1), (1.61, 2181, 1), (1.75, 2400, 1),
    (1.89, 2591, 1), (2.05, 2825, 1), (2.21, 3034, 1), (2.35, 3240, 1), (2.51, 3289, 1), (2.66, 3290, 1),
    (2.96, 3291, 1), (3.4, 3292, 1), (4.01, 3293, 1), (4.15, 3294, 2), (4.6, 3296, 2), (6.67, 3297, 3),
    (7.54, 3298, 4), (8.16, 3299, 5), (9.04, 3300, 5), (9.63, 3301, 5), (12.77, 3302, 5), (22.64, 3303, 5),
    (24.17, 3304, 5), (24.94, 3305, 5), (25.11, 3306, 5), (27.13, 3307, 5), (28.35, 3308, 5), (30.39, 3309, 5),
    (31.64, 3310, 6), (32.59, 3311, 6), (36.17, 3313, 6), (37.92, 3314, 6), (39.53, 3315, 7), (40.1, 3316, 7),
    (50.66, 3318, 7), (51.82, 3319, 7), (53.14, 3320, 7), (54.04, 3321, 7), (54.77, 3323, 7), (56.5, 3324, 7),
    (58.24, 3326, 7), (58.68, 3328, 7), (60.15, 3329, 7), (60.23, 3330, 7), (61.41, 3333, 7), (61.68, 3333, 7),
    (62.85, 3335, 7), (65.99, 3336, 7), (71.08, 3337, 7), (72.41, 3338, 7), (72.66, 3340, 8), (76.91, 3342, 8),
    (77.57, 3343, 8), (80.83, 3345, 8), (81.24, 3346, 8), (85.91, 3347, 8), (88.57, 3348, 8), (90.51, 3348, 8),
    (96.25, 3349, 8), (99.84, 3350, 8), (104.52, 3351, 8), (108.01, 3353, 9), (119.84, 3354, 9),
    (129.57, 3355, 9), (130.91, 3356, 9), (134.57, 3357, 9), (137.49, 3358, 9), (143.41, 3360, 9),
    (143.92, 3963, 87), (144.41, 4628, 87), (144.92, 5314, 87), (145.42, 6000, 87), (145.92, 6666, 87),
    (146.42, 7334, 87), (146.92, 7988, 87), (147.42, 8565, 87), (147.92, 9231, 87), (148.42, 9760, 87),
    (148.92, 10373, 87), (149.42, 11000, 87), (149.92, 11649, 87), (150.0, 11702, 87), (156.5, 11703, 87),
    (166.24, 11704, 87), (176.08, 11705, 87), (198.43, 11705, 87),
)


def _series(points=POINTS) -> PostSeries:
    return PostSeries(uuid4(), uuid4(), "vk", PUBLISHED, False,
                      tuple(PUBLISHED + timedelta(hours=age) for age, _, _ in points),
                      {Metric.VIEWS: tuple(v for _, v, _ in points), Metric.REACTIONS: tuple(r for _, _, r in points)},
                      qualities={Metric.VIEWS: ("exact",) * len(points), Metric.REACTIONS: ("exact",) * len(points)},
                      interval_uncertain=(False,) * len(points), publication_type="video")


def _hours(sign) -> tuple[float, float]:
    return tuple((moment - PUBLISHED).total_seconds() / 3600 for moment in (sign.interval.start, sign.interval.end))


def test_burst_background_is_taken_from_the_last_reading_five_hours_before() -> None:
    """Замер за 5 ч 55 мин до рывка — фон; ближайший за шесть часов был за 8 ч 50 мин."""
    series = _series()
    signs = bounded_reaction_burst.detect(prepare(series, series.observed_at[-1], CollectionCadence()),
                                          DetectorContext(series.platform))
    assert [sign for sign in signs if sign.render.get("kind") == "bounded_burst"]
