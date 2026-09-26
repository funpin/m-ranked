"""Подготовка рядов: сетка замеров, скорости, пробелы, качество, масштабы.

Единственное место, где решается, какие участки ряда пригодны для вывода.
Детекторы получают готовые сетки и маски и сами качество не оценивают.
Модуль чистый: без базы и без «сейчас» — момент анализа передаётся параметром.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from enum import IntFlag
from typing import Mapping

import numpy as np

from .domain import Metric, PostSeries

PREPARATION_VERSION = "2.1.0"

MINUTE, HOUR, DAY = 60, 3600, 86400

# Детекторы скорости смотрят на ряд сразу на нескольких масштабах: растянутый
# подъём, незаметный на пятиминутных барах, выпуклый на шестичасовых.
SCALES = (timedelta(minutes=15), timedelta(hours=1), timedelta(hours=6), timedelta(hours=24))

# Интервал между замерами длиннее трёх ожидаемых шагов — пробел: один-два
# пропущенных цикла сборщика ещё не пробел, а сбой на час при пятиминутном шаге уже он.
GAP_FACTOR = 3.0

# Падение счётчика до пятой части значения — снятые реакции и правки площадки;
# больше — сброс счётчика, через который скорость не считается.
RESET_FRACTION = 0.2
RESET_MIN_DROP = 10

# Возрастные интервалы таблицы расписания анализа: 0–24 ч, 1–3 сут, 3–7 сут,
# 7–30 сут и дальше. Индекс интервала — номер строки таблицы.
AGE_BAND_EDGES = np.array((0, DAY, 3 * DAY, 7 * DAY, 30 * DAY), dtype=np.float64)


class PointFlag(IntFlag):
    MISSING = 1
    NEGATIVE_DELTA = 2
    COUNTER_RESET = 4
    AFTER_GAP = 8


@dataclass(frozen=True, slots=True)
class CollectionCadence:
    """Шаг сбора по возрасту поста.

    Имена полей и переменных — те же, что у `Settings` сборщиков; тест сверяет
    значения по умолчанию, поэтому расхождение со сборщиками ловится в CI, а
    не на проде. Импортировать настройки сборщиков модулю запрещает изоляция.
    """

    poll_interval_minutes: int = 5
    second_day_poll_interval_minutes: int = 15
    third_day_poll_interval_minutes: int = 15
    days_4_to_6_poll_interval_minutes: int = 30
    days_7_to_13_poll_interval_minutes: int = 60
    day_14_plus_poll_interval_minutes: int = 60
    rutube_first_three_days_poll_interval_minutes: int = 60
    rutube_days_4_to_6_poll_interval_minutes: int = 180
    rutube_days_7_to_13_poll_interval_minutes: int = 360
    rutube_day_14_plus_poll_interval_minutes: int = 720
    track_post_for_hours: int = 720

    def __post_init__(self) -> None:
        if any(getattr(self, item.name) <= 0 for item in fields(self)):
            raise ValueError("collection cadence values must be positive")

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "CollectionCadence":
        values = {item.name: int(environ[item.name.upper()])
                  for item in fields(cls) if item.name.upper() in environ}
        return cls(**values)

    def expected_step_seconds(self, platform: str, ages: np.ndarray) -> np.ndarray:
        if platform == "rutube":
            edges = (3 * DAY, 7 * DAY, 14 * DAY)
            minutes = (self.rutube_first_three_days_poll_interval_minutes,
                       self.rutube_days_4_to_6_poll_interval_minutes,
                       self.rutube_days_7_to_13_poll_interval_minutes,
                       self.rutube_day_14_plus_poll_interval_minutes)
        else:
            edges = (DAY, 2 * DAY, 3 * DAY, 7 * DAY, 14 * DAY)
            minutes = (self.poll_interval_minutes, self.second_day_poll_interval_minutes,
                       self.third_day_poll_interval_minutes,
                       self.days_4_to_6_poll_interval_minutes,
                       self.days_7_to_13_poll_interval_minutes,
                       self.day_14_plus_poll_interval_minutes)
        band = np.searchsorted(np.asarray(edges, dtype=np.float64), ages, side="right")
        return np.asarray(minutes, dtype=np.float64)[band] * MINUTE


@dataclass(frozen=True, slots=True)
class Gap:
    """Прирост через пробел в замерах — материал только для паттерна 4."""

    start_age: float
    end_age: float
    delta: float


@dataclass(frozen=True, slots=True)
class Grid:
    """Равномерная сетка одного масштаба по одной метрике.

    `edges` — возраст границ ячеек, `rates` — прирост на ячейку, делённый на
    её длительность, в единицах в секунду. Ячейка `usable`, только если её
    целиком покрывают настоящие замеры без пробела и сброса счётчика.
    """

    scale: timedelta
    edges: np.ndarray
    cumulative: np.ndarray
    rates: np.ndarray
    usable: np.ndarray
    in_gap: np.ndarray
    negative: np.ndarray


@dataclass(frozen=True, slots=True)
class MetricSeries:
    metric: Metric
    # Только точки с полученным значением; флаги выровнены с ними.
    ages: np.ndarray
    values: np.ndarray
    flags: np.ndarray
    gaps: tuple[Gap, ...]
    grids: Mapping[timedelta, Grid]
    coverage: float
    # Просмотры репоста принадлежат источнику: детекторы, зависящие от
    # просмотров и нормы аккаунта, такую метрику пропускают.
    source_counter: bool


@dataclass(frozen=True, slots=True)
class PreparedSeries:
    series: PostSeries
    analyzed_at: datetime
    ages: np.ndarray
    age_bands: np.ndarray
    expected_steps: np.ndarray
    metrics: Mapping[Metric, MetricSeries]
    unsupported: frozenset[Metric]
    truncated_start: bool
    stale_seconds: float


def age_band(ages: np.ndarray) -> np.ndarray:
    """Возрастной интервал таблицы периодичности, 0–4.

    Сетка выравнивается по границам масштаба и может начинаться чуть раньше
    публикации; такая ячейка — первый интервал, а не несуществующий «−1».
    """
    bands = np.searchsorted(AGE_BAND_EDGES, ages, side="right") - 1
    return np.clip(bands, 0, AGE_BAND_EDGES.size - 1)


def prepare(series: PostSeries, analyzed_at: datetime, cadence: CollectionCadence,
            scales: tuple[timedelta, ...] = SCALES) -> PreparedSeries:
    published = series.published_at.timestamp()
    instants = np.fromiter((item.timestamp() for item in series.observed_at),
                           dtype=np.float64, count=len(series.observed_at))
    keep = instants <= analyzed_at.timestamp()
    columns = {metric: np.asarray(column, dtype=np.float64)[keep] for metric, column in series.values.items()}
    collected = np.fromiter((item.timestamp() for item in series.collected), dtype=np.float64,
                            count=len(series.collected))
    collected = collected[collected <= analyzed_at.timestamp()] - published
    raw_ages, rows, covered = confirm_unchanged(instants[keep] - published, collected, cadence, series.platform)
    ages = _frozen(raw_ages)
    steps = _frozen(cadence.expected_step_seconds(series.platform, ages))
    metrics: dict[Metric, MetricSeries] = {}
    for metric, column in columns.items():
        raw = column[rows]
        prepared = _metric(metric, ages, raw, series, cadence, scales, covered)
        if prepared is not None:
            metrics[metric] = prepared
    first_step = cadence.expected_step_seconds(series.platform, np.zeros(1))[0]
    return PreparedSeries(
        series, analyzed_at, ages, _frozen(age_band(ages)), steps, metrics,
        frozenset(Metric) - frozenset(metrics),
        # Ранняя часть затухания без первых замеров не оценивается.
        truncated_start=bool(ages.size) and float(ages[0]) > first_step,
        stale_seconds=float(analyzed_at.timestamp() - published - ages[-1]) if ages.size else 0.0,
    )


def confirm_unchanged(ages: np.ndarray, collected: np.ndarray, cadence: CollectionCadence,
                      platform: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Отличить «не менялось» от «нет данных» по журналу сбора аккаунта.

    Сборщик пишет замер, только когда значения изменились, поэтому плато —
    именно тот участок, где замеров нет. Без журнала такой участок выглядел
    пробелом, и рывок, обрывающийся в плато, не судился вовсе.

    Интервал между замерами подтверждён, если успешные циклы сбора шли по
    нему без разрыва длиннее трёх ожидаемых шагов. Цикл опрашивает пост, как
    только тот должен по своему шагу, поэтому значение не менялось как минимум
    до «последний цикл минус шаг»: там ставится перенесённая точка с прежним
    значением. Прирост остаётся на последнем шаге перед новым замером, а не
    размазывается по всему интервалу. Цикл, оборвавшийся на простое, делит
    интервал: до простоя — подтверждено, дальше — пробел. После последнего
    замера так же продлевается хвост до последнего цикла.

    Возвращает возрасты точек, индекс исходной строки для каждой (перенесённая
    точка берёт значения предыдущей) и `covered[k]` — участок от точки k−1 до
    k подтверждён журналом.
    """
    size = ages.size
    rows = np.arange(size)
    covered = np.zeros(size, dtype=bool)
    if size == 0 or not collected.size:
        return ages, rows, covered
    collected = np.sort(collected[collected > ages[0]])

    def chain(start: float, stop: float, limit: float) -> float:
        """Последний цикл непрерывной цепочки от start, не дальше stop."""
        left, right = np.searchsorted(collected, (start, stop), side="right")
        inside = collected[left:right]
        if not inside.size:
            return start
        broken = np.flatnonzero(np.diff(np.concatenate(([start], inside))) > limit)
        return float(inside[broken[0] - 1]) if broken.size else float(inside[-1])

    steps = np.maximum(cadence.expected_step_seconds(platform, ages[:-1]),
                       cadence.expected_step_seconds(platform, ages[1:]))
    limits = GAP_FACTOR * steps
    covered[1:] = np.diff(ages) <= limits
    # Перенесённые точки: (позиция вставки, возраст, строка-источник).
    inserts: list[tuple[int, float, int]] = []
    for index in np.flatnonzero(~covered[1:]):
        start, stop, step = float(ages[index]), float(ages[index + 1]), float(steps[index])
        last = chain(start, stop, limits[index])
        covered[index + 1] = stop - last <= limits[index]
        if last - step > start + step / 2:
            inserts.append((index + 1, last - step, index))
    tail = float(ages[-1])
    step = float(cadence.expected_step_seconds(platform, np.array((tail,)))[0])
    last = chain(tail, np.inf, GAP_FACTOR * step)
    if last - step > tail + step / 2:
        inserts.append((size, last - step, size - 1))
    if not inserts:
        return ages, rows, covered
    where = np.array([item[0] for item in inserts])
    return (np.insert(ages, where, [item[1] for item in inserts]),
            np.insert(rows, where, [item[2] for item in inserts]),
            # Участок до перенесённой точки подтверждён; следующий за ней
            # наследует прежний признак исходного интервала.
            np.insert(covered, where, True))


def _metric(metric: Metric, all_ages: np.ndarray, raw: np.ndarray, series: PostSeries,
            cadence: CollectionCadence, scales: tuple[timedelta, ...],
            covered: np.ndarray | None = None) -> MetricSeries | None:
    present = ~np.isnan(raw)
    # Столбец без единого значения — площадка метрику не отдаёт, это не ноль.
    if not present.any():
        return None
    positions = np.flatnonzero(present)
    ages, values = all_ages[present], raw[present]
    flags = np.zeros(values.size, dtype=np.uint8)
    if not present.all():
        # Пропуск метрики в замере помечает соседнюю справа полученную точку.
        missing_before = np.cumsum(~present)[present]
        flags[1:][np.diff(missing_before) > 0] |= np.uint8(PointFlag.MISSING)
    delta = np.diff(values)
    elapsed = np.diff(ages)
    reset = -delta > np.maximum(RESET_MIN_DROP, RESET_FRACTION * values[:-1])
    negative = (delta < 0) & ~reset
    expected = np.maximum(cadence.expected_step_seconds(series.platform, ages[:-1]),
                          cadence.expected_step_seconds(series.platform, ages[1:]))
    gap = elapsed > GAP_FACTOR * expected
    if covered is not None and covered.size == all_ages.size:
        # Подтверждение журналом годится только для соседних точек: метрика,
        # пропавшая в замерах между ними, — это отсутствие данных именно по ней.
        direct = np.diff(positions) == 1
        gap &= ~(direct & covered[positions[1:]])
    flags[1:][negative] |= np.uint8(PointFlag.NEGATIVE_DELTA)
    flags[1:][reset] |= np.uint8(PointFlag.COUNTER_RESET)
    flags[1:][gap] |= np.uint8(PointFlag.AFTER_GAP)
    gap_index = np.flatnonzero(gap)
    gaps = tuple(Gap(float(ages[index]), float(ages[index + 1]), float(delta[index]))
                 for index in gap_index)
    span = float(ages[-1] - ages[0])
    coverage = 1.0 if span <= 0 else 1.0 - float(elapsed[gap].sum()) / span
    grids = {scale: _grid(scale, ages, values, gap, reset, negative) for scale in scales}
    return MetricSeries(
        metric, _frozen(ages), _frozen(values), _frozen(flags), gaps, grids, coverage,
        source_counter=series.is_repost and metric is Metric.VIEWS,
    )


def _grid(scale: timedelta, ages: np.ndarray, values: np.ndarray, gap: np.ndarray,
          reset: np.ndarray, negative: np.ndarray) -> Grid:
    width = scale.total_seconds()
    first, last = np.ceil(ages[0] / width), np.floor(ages[-1] / width)
    edges = np.arange(first, last + 1, dtype=np.float64) * width
    if edges.size < 2:
        empty = np.zeros(0, dtype=np.float64)
        flag = np.zeros(0, dtype=bool)
        return Grid(scale, _frozen(edges), _frozen(np.interp(edges, ages, values)),
                    _frozen(empty), _frozen(flag), _frozen(flag), _frozen(flag))
    cumulative = np.interp(edges, ages, values)
    rates = np.diff(cumulative) / width
    # Сегмент j — между замерами j и j+1. Ячейка задевает сегменты от того, в
    # котором лежит её начало, до последнего, начавшегося раньше её конца;
    # префиксные суммы отвечают «есть ли среди них плохой» без цикла.
    last_segment = ages.size - 2
    start = np.clip(np.searchsorted(ages, edges[:-1], side="right") - 1, 0, last_segment)
    stop = np.clip(np.searchsorted(ages, edges[1:], side="left"), 1, last_segment + 1)

    def touched(bad: np.ndarray) -> np.ndarray:
        prefix = np.concatenate(([0], np.cumsum(bad)))
        return prefix[stop] - prefix[start] > 0

    in_gap = touched(gap)
    usable = ~(in_gap | touched(reset))
    return Grid(scale, _frozen(edges), _frozen(cumulative), _frozen(rates), _frozen(usable),
                _frozen(in_gap), _frozen(touched(negative)))


def _frozen(array: np.ndarray) -> np.ndarray:
    array.setflags(write=False)
    return array
