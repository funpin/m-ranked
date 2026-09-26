"""Общий контракт детекторов v2.

Детектор — модуль с константами `ID`, `VERSION`, `PATTERN`, `FAMILY`,
`NEEDS_NORM` и чистой функцией `detect(prepared, context)`. Всё, что нужно
нескольким детекторам сразу, — подгонка затухания по ранней части ряда,
агрегаты соседних постов, форматирование формул — живёт здесь и считается
один раз на пост.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Collection, Mapping, Protocol, Sequence
from uuid import UUID

import numpy as np

from ..domain import Family, Interval, Metric, PostSeries, Sign
from ..norms import DECAY_EXPONENT_BOUNDS, DecayFit, Norm, fit_decay
from ..series import DAY, HOUR, CollectionCadence, PreparedSeries, confirm_unchanged

# Счётчики площадок обновляются с задержкой; реакция может «обогнать»
# просмотр на эту величину без всякой аномалии. Telegram обновляет
# просмотры почти сразу, ВК и MAX — пакетами, RuTube — реже всех.
COUNTER_DELAY_SECONDS = {"telegram": 15 * 60, "vk": 30 * 60, "max": 30 * 60, "rutube": 2 * HOUR}

# Ранняя часть ряда для собственной модели затухания — первые сутки: у
# любой площадки основная волна внимания приходится на них (исследование, раздел 2).
FIT_UNTIL_AGE = DAY
FIT_MIN_CELLS = 8
# Нижняя граница модельного разброса в лог-шкале: суточный ритм и шум
# сбора не дают органике ложиться на кривую точнее чем на ±10 %.
MODEL_SIGMA_FLOOR = 0.1


class Detector(Protocol):
    ID: str
    VERSION: str
    PATTERN: int
    FAMILY: Family
    NEEDS_NORM: bool

    def detect(self, prepared: PreparedSeries, context: "DetectorContext") -> tuple[Sign, ...]: ...


@dataclass(frozen=True, slots=True)
class SiblingActivity:
    """Почасовые приросты других постов аккаунта на общей оси настенного времени.

    Детектору синхронности нужны не сырые ряды, а приросты по часам: так
    память не растёт с числом соседей. NaN — час не покрыт замерами поста.
    """

    hours: np.ndarray
    reactions: np.ndarray
    views: np.ndarray
    ages: np.ndarray
    publications: tuple[UUID, ...] = ()

    @classmethod
    def from_series(cls, siblings: Sequence[PostSeries], start: float, end: float) -> "SiblingActivity | None":
        first, last = int(np.floor(start / HOUR)), int(np.ceil(end / HOUR))
        if not siblings or last - first < 2:
            return None
        edges = np.arange(first, last + 1, dtype=np.float64) * HOUR
        rows = {Metric.REACTIONS: [], Metric.VIEWS: []}
        ages = []
        for series in siblings:
            published = series.published_at.timestamp()
            instants = np.fromiter((item.timestamp() for item in series.observed_at), dtype=np.float64)
            collected = np.fromiter((item.timestamp() for item in series.collected), dtype=np.float64)
            # Те же подтверждённые журналом участки «без изменений», что и в
            # подготовке ряда: тихий час — ноль прироста, а не «нет данных».
            ages_, source, covered = confirm_unchanged(instants - published, collected - published,
                                                      CollectionCadence(), series.platform)
            ages.append(edges[:-1] - published)
            for metric, bucket in rows.items():
                column = series.values.get(metric)
                values = None if column is None else np.asarray(column, dtype=np.float64)[source]
                bucket.append(_hourly(ages_ + published, values, edges, covered))
        return cls(edges[:-1] / HOUR, np.vstack(rows[Metric.REACTIONS]), np.vstack(rows[Metric.VIEWS]),
                   np.vstack(ages), tuple(item.publication_id for item in siblings))

    @classmethod
    def from_hourly(cls, rows: Sequence[Mapping[str, Any]], first_hour: int, last_hour: int,
                    collected_hours: Collection[int] = ()) -> "SiblingActivity | None":
        """Из почасовых максимумов счётчиков: прирост часа — разность с предыдущим часом.

        `collected_hours` — часы с успешным циклом сбора аккаунта. Сборщик пишет
        замер только при изменении, поэтому такой час без замера несёт прежний
        уровень поста; час без цикла остаётся «нет данных» и рвёт перенос."""
        posts: dict[UUID, list[Mapping[str, Any]]] = {}
        for row in rows:
            posts.setdefault(row["publication_id"], []).append(row)
        if not posts or last_hour - first_hour < 2:
            return None
        hours = np.arange(first_hour, last_hour, dtype=np.float64)
        shape = (len(posts), hours.size)
        reactions, views, ages = np.full(shape, np.nan), np.full(shape, np.nan), np.zeros(shape)
        for index, items in enumerate(posts.values()):
            ages[index] = hours * HOUR - items[0]["published_at"].timestamp()
            for target, key in ((reactions, "reactions"), (views, "views")):
                level = np.full(hours.size + 1, np.nan)
                for row in items:
                    position = int(row["hour"]) - first_hour + 1
                    if 0 <= position <= hours.size and row[key] is not None:
                        level[position] = float(row[key])
                carry = np.nan
                for position in range(level.size):
                    if not np.isnan(level[position]):
                        carry = level[position]
                    elif first_hour - 1 + position in collected_hours:
                        level[position] = carry
                    else:
                        carry = np.nan
                target[index] = np.diff(level)
        return cls(hours, reactions, views, ages, tuple(posts))

    def without(self, publication_id: UUID) -> "SiblingActivity | None":
        keep = [index for index, item in enumerate(self.publications) if item != publication_id]
        if not keep:
            return None
        return SiblingActivity(self.hours, self.reactions[keep], self.views[keep], self.ages[keep],
                               tuple(self.publications[index] for index in keep))


def _hourly(instants: np.ndarray, column, edges: np.ndarray,
            covered: np.ndarray | None = None) -> np.ndarray:
    result = np.full(edges.size - 1, np.nan)
    if column is None:
        return result
    values = np.asarray(column, dtype=np.float64)
    keep = ~np.isnan(values)
    # Подтверждение журналом годится только для соседних точек (как в series).
    confirmed = None
    if covered is not None:
        positions = np.flatnonzero(keep)
        confirmed = (np.diff(positions) == 1) & covered[positions[1:]]
    instants, values = instants[keep], values[keep]
    if values.size < 2:
        return result
    cumulative = np.interp(edges, instants, values)
    inside = (edges[:-1] >= instants[0]) & (edges[1:] <= instants[-1])
    # Час, внутри которого замеры разошлись больше чем на три часа, не покрыт.
    spacing = np.diff(instants)
    left = np.clip(np.searchsorted(instants, edges[:-1], side="right") - 1, 0, spacing.size - 1)
    right = np.clip(np.searchsorted(instants, edges[1:], side="left") - 1, 0, spacing.size - 1)
    short = spacing <= 3 * HOUR if confirmed is None else (spacing <= 3 * HOUR) | confirmed
    covered = short[left] & short[right]
    delta = np.diff(cumulative)
    result[inside & covered] = delta[inside & covered]
    return result


@dataclass(frozen=True, slots=True)
class EarlyFit:
    """Собственное затухание поста по первым суткам, в единицах в час."""

    decay: DecayFit
    sigma_model: float

    def expected(self, start_age: np.ndarray, end_age: np.ndarray) -> np.ndarray:
        """Ожидаемый прирост между возрастами — интеграл модели."""
        low = np.asarray(start_age, dtype=np.float64) / HOUR + self.decay.c
        high = np.asarray(end_age, dtype=np.float64) / HOUR + self.decay.c
        b, a = self.decay.b, self.decay.a
        if abs(b - 1) < 1e-9:
            return a * (np.log(high) - np.log(low))
        return a / (1 - b) * (high ** (1 - b) - low ** (1 - b))


@dataclass
class DetectorContext:
    platform: str
    norm: Norm | None = None
    siblings: SiblingActivity | None = None
    subscriber_ages: np.ndarray = field(default_factory=lambda: np.zeros(0))
    subscriber_counts: np.ndarray = field(default_factory=lambda: np.zeros(0))
    _fits: dict = field(default_factory=dict)

    @property
    def norm_confidence(self) -> float:
        return 0.0 if self.norm is None else float(self.norm.confidence)

    @property
    def counter_delay(self) -> float:
        return float(COUNTER_DELAY_SECONDS[self.platform])

    def early_fit(self, prepared: PreparedSeries, metric: Metric) -> EarlyFit | None:
        if metric not in self._fits:
            self._fits[metric] = _early_fit(prepared, metric, self.norm)
        return self._fits[metric]

    def subscriber_growth(self, start_age: float, end_age: float) -> float | None:
        """Относительный прирост подписчиков за окно; None — данных нет."""
        ages, counts = self.subscriber_ages, self.subscriber_counts
        if ages.size < 2 or start_age < ages[0] or end_age > ages[-1]:
            return None
        before, after = np.interp((start_age, end_age), ages, counts)
        # Фон — обычный прирост за такое же окно до события.
        width = end_age - start_age
        if start_age - width >= ages[0]:
            earlier = float(np.interp(start_age - width, ages, counts))
            baseline = before - earlier
        else:
            baseline = 0.0
        return float((after - before - max(0.0, baseline)) / max(before, 1.0))


def _early_fit(prepared: PreparedSeries, metric: Metric, norm: Norm | None) -> EarlyFit | None:
    data = prepared.metrics.get(metric)
    if data is None or prepared.truncated_start:
        return None
    grid = data.grids.get(timedelta(hours=1))
    if grid is None or not grid.rates.size:
        return None
    middle = (grid.edges[:-1] + grid.edges[1:]) / 2
    keep = grid.usable & (middle < FIT_UNTIL_AGE) & (grid.rates > 0)
    if keep.sum() < FIT_MIN_CELLS:
        return None
    hours = middle[keep] / HOUR
    rates = grid.rates[keep] * HOUR
    bounds = DECAY_EXPONENT_BOUNDS
    # Норма задаёт форму: показатель поста не уходит от нормы площадки дальше,
    # чем допускает якорь нормы аккаунта.
    reference = None if norm is None else norm.decay.get(metric.value)
    if reference is not None:
        bounds = (max(bounds[0], reference.b - 0.35), min(bounds[1], reference.b + 0.35))
    fit = fit_decay(hours, rates, exponent_bounds=bounds)
    if fit is None:
        return None
    residual = np.log(rates) - np.log(fit.rate(hours))
    spread = 1.4826 * float(np.median(np.abs(residual - np.median(residual))))
    poisson = float(np.mean(1.0 / np.maximum(fit.rate(hours), 1e-9)))
    sigma = float(np.sqrt(max(spread ** 2 - poisson, MODEL_SIGMA_FLOOR ** 2)))
    return EarlyFit(fit, sigma)


def make_sign(pattern: int, family: Family, prepared: PreparedSeries, metric: Metric, strength: float,
              start_age: float, end_age: float, scale: timedelta, formula: str,
              render: Mapping[str, Any], alternatives: tuple[str, ...] = (),
              norm_confidence: float | None = None) -> Sign:
    published = prepared.series.published_at
    end_age = max(end_age, start_age + 1)
    return Sign(pattern, family, metric, float(np.clip(strength, 0, 1)),
                Interval(published + timedelta(seconds=float(start_age)),
                         published + timedelta(seconds=float(end_age))),
                scale, formula, {"startAge": round(float(start_age)), "endAge": round(float(end_age)), **render},
                alternatives, norm_confidence)


def age_text(seconds: float) -> str:
    """Возраст поста для формулы: 1д21ч, 7ч, 45мин."""
    minutes = int(round(seconds / 60))
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days}д{hours}ч" if hours else f"{days}д"
    if hours:
        return f"{hours}ч{minutes:02d}м" if minutes else f"{hours}ч"
    return f"{minutes}мин"


def number(value: float) -> str:
    """Целое с разделителем разрядов: 1 170, 26 000."""
    return f"{round(value):,}".replace(",", " ")


def scale_text(scale: timedelta) -> str:
    seconds = scale.total_seconds()
    return f"{int(seconds // HOUR)} ч" if seconds >= HOUR else f"{int(seconds // 60)} мин"


def pelt(values: np.ndarray, penalty: float) -> list[int]:
    """Точки излома кусочно-постоянного среднего (Killick и др., 2012).

    Возвращает границы сегментов, включая 0 и len(values). Стоимость —
    сумма квадратов отклонений от среднего сегмента; на рядах из десятков
    ячеек отсечение PELT держит внутренний цикл коротким.
    """
    n = values.size
    first = np.concatenate(([0.0], np.cumsum(values)))
    second = np.concatenate(([0.0], np.cumsum(values * values)))
    best = np.zeros(n + 1)
    best[0] = -penalty
    previous = np.zeros(n + 1, dtype=np.int64)
    candidates = np.array([0], dtype=np.int64)
    for end in range(1, n + 1):
        length = end - candidates
        total = first[end] - first[candidates]
        cost = second[end] - second[candidates] - total * total / length
        scores = best[candidates] + cost + penalty
        choice = int(np.argmin(scores))
        best[end] = scores[choice]
        previous[end] = candidates[choice]
        candidates = np.append(candidates[scores - penalty <= best[end]], end)
    bounds = [n]
    while bounds[-1] > 0:
        bounds.append(int(previous[bounds[-1]]))
    return bounds[::-1]


def expected_step(prepared: PreparedSeries, ages: np.ndarray) -> np.ndarray:
    """Ожидаемый шаг сбора в заданных возрастах."""
    if not prepared.ages.size:
        return np.zeros_like(ages)
    return np.interp(ages, prepared.ages, prepared.expected_steps)


def strongest(signs: Sequence[Sign]) -> list[Sign]:
    """Один участок на разных масштабах — один признак, с масштабом, где он сильнее."""
    kept: list[Sign] = []
    for sign in sorted(signs, key=lambda item: -item.strength):
        if not any(item.metric is sign.metric and item.interval.start < sign.interval.end
                   and sign.interval.start < item.interval.end for item in kept):
            kept.append(sign)
    return kept
