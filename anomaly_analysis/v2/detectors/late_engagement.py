"""Поздняя вовлечённость выше ранней: реакции на поздние просмотры поста.

Внимание к посту стареет (Vassio et al., 2022; Crane & Sornette, 2008): в
первые сутки его видят подписчики, которые реагируют охотнее всего, позже —
случайные и архивные читатели, реагирующие реже. Поэтому доля реакций на
поздние просмотры у живого поста ниже ранней: по 81 аккаунту MAX медиана
отношения поздней доли к ранней около 0,17, у ВК из-за рекомендаций — около
0,6 (research/smart-engagement-2026-09, TAIL_RATIO.md).

Детектор сравнивает пост с самим собой, а не с историей аккаунта: постоянная
добавка реакций к старым постам не становится «нормой» оттого, что
повторяется месяцами. Нулевая гипотеза щедрая — поздние зрители реагируют
не реже ранних: ΔR ~ Poisson(q₂₄ · ΔV). Признак — прирост реакций, который
при ней почти невозможен, и сама доля хотя бы вдвое выше ранней.

Сила не выше средней: ровно так выглядят и живые обстоятельства — пост
попал в подборку заинтересованной аудитории, его переслали в профильный чат,
на архив пришёл новый увлечённый читатель. Происхождение реакций по
счётчикам не устанавливается.
"""
from __future__ import annotations

from datetime import timedelta
import math

from scipy.stats import poisson

from ..domain import Family, Metric, Sign
from ..series import PreparedSeries
from ..tail_ledger import build_ledger
from .base import DetectorContext, age_text, make_sign, number

ID = "late_engagement"
VERSION = "1.0.0"
PATTERN = 13
FAMILY = Family.CROSS_METRIC
NEEDS_NORM = False

MEASUREMENT_MODE = "late_engagement_v1"
# Поздняя доля должна быть хотя бы вдвое выше ранней.
MIN_RATIO = 2.0
# Меньше десятка поздних реакций — это один-два читателя, а не картина.
MIN_LATE_REACTIONS = 10
# Ранняя доля определяется по достаточному числу просмотров.
MIN_EARLY_VIEWS = 50
# −log10 p: от 4 (одна на десять тысяч) — признак; от 10 — предел силы.
MIN_SURPRISE = 4.0
FULL_SURPRISE = 10.0
MIN_STRENGTH = 0.45
MAX_STRENGTH = 0.6


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    ledger = build_ledger(prepared.series, prepared.analyzed_at)
    late = ledger.late
    early = ledger.early
    # Округлённые счётчики Telegram годятся для сравнения аккаунтов, но не для признака поста.
    if ledger.rounded or late is None or early is None or early.views < MIN_EARLY_VIEWS:
        return ()
    late_views, late_reactions = late
    if late_reactions < MIN_LATE_REACTIONS:
        return ()
    early_rate = (early.reactions + 0.5) / (early.views + 1)
    late_rate = (late_reactions + 0.5) / (late_views + 1)
    ratio = late_rate / early_rate
    if ratio < MIN_RATIO:
        return ()
    expected = early_rate * late_views
    surprise = _surprise(late_reactions, expected)
    if surprise < MIN_SURPRISE:
        return ()
    strength = MIN_STRENGTH + (MAX_STRENGTH - MIN_STRENGTH) * min(
        1.0, (surprise - MIN_SURPRISE) / (FULL_SURPRISE - MIN_SURPRISE))
    start, end = ledger.start, ledger.end
    formula = (f"с {age_text(start.age)} до {age_text(end.age)}: +{number(late_reactions)} реакций "
               f"на +{number(late_views)} просмотров ({_percent(late_rate)}), "
               f"в первые сутки {number(early.reactions)} на {number(early.views)} "
               f"({_percent(early_rate)}); поздняя доля в {_decimal(ratio)} раза выше ранней, "
               f"при ранней доле ожидалось ≈{number(expected)}")
    return (make_sign(PATTERN, FAMILY, prepared, Metric.REACTIONS, strength, start.age, end.age,
                      timedelta(seconds=end.age - start.age), formula,
                      {"kind": "late_engagement", "measurementMode": MEASUREMENT_MODE,
                       "earlyRate": round(early_rate, 5), "lateRate": round(late_rate, 5),
                       "ratio": round(ratio, 3), "lateReactions": late_reactions, "lateViews": late_views,
                       "earlyReactions": early.reactions, "earlyViews": early.views,
                       "expected": round(expected, 1), "surprise": round(surprise, 2)},
                      ("interested_audience_found_post", "returning_readers", "forward_by_large_channel")),)


def _surprise(observed: int, expected: float) -> float:
    """−log10 P(X ≥ observed) при X ~ Poisson(expected)."""
    tail = float(poisson.sf(observed - 1, max(expected, 1e-9)))
    if tail > 0:
        return -math.log10(tail)
    # Вне точности double — хвост заведомо мельче любого порога.
    return FULL_SURPRISE


def _percent(rate: float) -> str:
    return f"{_decimal(rate * 100)} %"


def _decimal(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")
