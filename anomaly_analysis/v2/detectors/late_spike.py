"""Поздний скачок: прирост, несовместимый с затуханием поста.

Модель затухания подгоняется по первым суткам поста (форму ограничивает норма
площадки) и продолжается дальше; ожидаемый прирост на окне — её интеграл.
Статистика — z логарифма «факт/ожидание» с разбросом модели и пуассоновским
разбросом самого окна: на мелких ячейках растянутый подъём тонет в шуме, на
крупных — выпуклый (паттерн 3 — тот же признак на другом масштабе).

Поздняя волна бывает честной: пересылка крупным каналом приносит новую волну
со своим степенным затуханием и живые реакции примерно в норме поста
(исследование, раздел 6). Такая волна — не выше слабого сигнала, а при
одновременном росте подписчиков или репостов ещё ниже. Прямая, ступенька
или волна без реакций остаются сильным признаком.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from ..domain import Family, Metric, Sign
from ..series import DAY, HOUR, PreparedSeries
from .base import DetectorContext, age_text, expected_step, make_sign, number, scale_text, strongest

ID = "late_spike"
VERSION = "2.0.0"
PATTERN = 2
FAMILY = Family.SHAPE
NEEDS_NORM = True

SCALES = (timedelta(minutes=15), timedelta(hours=1), timedelta(hours=6))
METRICS = (Metric.VIEWS, Metric.REACTIONS)
# «Поздний» — после первых суток, по которым подогнана модель.
LATE_AGE = DAY
CANDIDATE_Z = 3.0
MIN_Z = 4.0
MIN_EXCESS = {Metric.VIEWS: 50, Metric.REACTIONS: 20}
# Скачок меньше 3 % значения на начало не меняет картину поста, даже если он
# статистически значим.
MIN_SHARE = 0.03
# Согласованность: доля реакций в приросте волны отличается от доли поста
# не больше чем втрое — живая новая аудитория реагирует примерно как старая.
CONSISTENCY = 3.0
# Честная волна не поднимается выше слабого сигнала; с внешним подтверждением
# (подписчики, репосты ВК) — ещё ниже.
NATURAL_CAP = 0.55
CONFIRMED_CAP = 0.35
SUBSCRIBER_GROWTH = 0.005
CONFIRM_BEFORE = 3 * HOUR
CONFIRM_AFTER = 6 * HOUR
# Форма на часовых ячейках. «Тело» скачка — часы не ниже 30 % пикового
# избытка. Ровное тело из трёх часов с разбросом до 30 % — прямая; обрыв до
# 5 % пика сразу за телом — ступенька. Живая волна за телом ещё держит
# десятки процентов пика и спадает постепенно.
BODY_SHARE = 0.3
RAMP_CELLS = 3
RAMP_CV = 0.3
STEP_SHARE = 0.05
TAIL_CELLS = 6
PARTNER = {Metric.VIEWS: Metric.REACTIONS, Metric.REACTIONS: Metric.VIEWS}
NAMES = {Metric.VIEWS: "просмотры", Metric.REACTIONS: "реакции"}


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    if prepared.series.is_repost:
        return ()
    signs = []
    for metric in METRICS:
        data = prepared.metrics.get(metric)
        fit = context.early_fit(prepared, metric)
        if data is None or fit is None or data.source_counter:
            continue
        for scale in SCALES:
            grid = data.grids.get(scale)
            if grid is not None and grid.rates.size:
                signs.extend(_scan(prepared, context, metric, fit, grid))
    return tuple(strongest(signs))


def _scan(prepared, context, metric, fit, grid):
    width = grid.scale.total_seconds()
    starts, ends = grid.edges[:-1], grid.edges[1:]
    fact = np.diff(grid.cumulative)
    expected = np.maximum(fit.expected(starts, ends), 0.0)
    sigma = np.sqrt(fit.sigma_model ** 2 + 1.0 / (expected + 0.5))
    z = np.log((fact + 0.5) / (expected + 0.5)) / sigma
    # Ячейка мельче шага сбора — интерполяция, а не наблюдение.
    valid = grid.usable & (starts >= LATE_AGE) & (expected_step(prepared, starts) <= width)
    hot = valid & (z >= CANDIDATE_Z)
    edges = np.flatnonzero(np.diff(np.concatenate(([0], hot.astype(np.int8), [0]))))
    signs = []
    for begin, end in zip(edges[::2], edges[1::2]):
        actual, model = float(fact[begin:end].sum()), float(expected[begin:end].sum())
        run_z = np.log((actual + 0.5) / (model + 0.5)) / np.sqrt(fit.sigma_model ** 2 + 1.0 / (model + 0.5))
        start_value = float(grid.cumulative[begin])
        if run_z < MIN_Z or actual - model < max(MIN_EXCESS[metric], MIN_SHARE * start_value):
            continue
        start_age, end_age = float(starts[begin]), float(ends[end - 1])
        strength = 0.5 + 0.5 * min(1.0, (run_z - MIN_Z) / 8)
        shape = _shape(prepared, context, metric, start_age, end_age)
        consistent = _consistent(prepared, context, metric, start_age, end_age)
        alternatives: tuple[str, ...] = ("news_event", "pinned_post", "forward_by_large_channel")
        if consistent and shape == "wave":
            strength = min(strength, NATURAL_CAP)
            alternatives = ("forward_by_large_channel", "recommendation_wave", "news_event")
            if _confirmed(prepared, context, start_age, end_age):
                strength = min(strength, CONFIRMED_CAP)
        formula = (f"{NAMES[metric]}: факт {number(actual)} против ожидаемых {number(model)} "
                   f"(×{(actual + 0.5) / (model + 0.5):.1f}, z = {run_z:.1f}), "
                   f"t ∈ [{age_text(start_age)}; {age_text(end_age)}], виден на масштабе {scale_text(grid.scale)}")
        signs.append(make_sign(
            PATTERN, FAMILY, prepared, metric, strength, start_age, end_age, grid.scale, formula,
            {"kind": "expected", "actual": round(actual), "expected": round(model, 1),
             "shape": shape, "consistent": consistent,
             "decay": [round(fit.decay.a, 4), round(fit.decay.b, 4), round(fit.decay.c, 4)]},
            alternatives, context.norm_confidence))
    return signs


def _excess(prepared, context, metric, start_age, end_age):
    """Избыток над моделью по часам — от начала скачка и ещё несколько часов после."""
    data = prepared.metrics[metric]
    grid = data.grids[timedelta(hours=1)]
    fit = context.early_fit(prepared, metric)
    starts = grid.edges[:-1]
    begin = int(np.searchsorted(starts, start_age, side="left"))
    run_end = int(np.searchsorted(starts, end_age, side="left"))
    stop = min(starts.size, run_end + TAIL_CELLS)
    excess = np.diff(grid.cumulative)[begin:stop] - fit.expected(starts[begin:stop], grid.edges[begin + 1:stop + 1])
    return excess, run_end - begin


def _shape(prepared, context, metric, start_age, end_age) -> str:
    excess, run = _excess(prepared, context, metric, start_age, end_age)
    if not excess.size or run <= 0:
        return "wave"
    peak = float(excess[:run].max())
    if peak <= 0:
        return "wave"
    last = int(np.flatnonzero(excess[:run] >= BODY_SHARE * peak)[-1]) + 1
    body = excess[:last]
    if body.size >= RAMP_CELLS and body.std() / body.mean() <= RAMP_CV:
        return "ramp"
    after = excess[last:last + 2]
    if after.size and float(np.maximum(after, 0).mean()) <= STEP_SHARE * peak:
        return "step"
    return "wave"


def _consistent(prepared, context, metric, start_age, end_age) -> bool:
    """Партнёрская метрика дала избыток в той же пропорции, что и до скачка.

    Сравниваются избытки над моделями обеих метрик, а не полные приросты: иначе
    органический фон партнёра замаскировал бы волну, пришедшую без него.
    """
    partner = PARTNER[metric]
    own, other = prepared.metrics[metric], prepared.metrics.get(partner)
    own_fit, other_fit = context.early_fit(prepared, metric), context.early_fit(prepared, partner)
    if other is None:
        return False
    tail = end_age + TAIL_CELLS * HOUR
    own_excess = _window_excess(own, own_fit, start_age, tail)
    other_excess = _window_excess(other, other_fit, start_age, tail)
    own_before = float(np.interp(start_age, own.ages, own.values))
    other_before = float(np.interp(start_age, other.ages, other.values))
    if own_excess <= 0 or own_before <= 0 or other_before <= 0:
        return False
    ratio = (max(other_excess, 0.0) / own_excess) / (other_before / own_before)
    return 1 / CONSISTENCY <= ratio <= CONSISTENCY


def _window_excess(data, fit, start_age: float, end_age: float) -> float:
    actual = float(np.interp(end_age, data.ages, data.values) - np.interp(start_age, data.ages, data.values))
    if fit is None:
        return actual
    return actual - float(fit.expected(np.array([start_age]), np.array([end_age]))[0])


def _confirmed(prepared, context, start_age, end_age) -> bool:
    """Внешнее подтверждение толчка: приток подписчиков или репостов ВК."""
    # Подписчики снимаются редко, раз в несколько часов: окно шире самого скачка.
    growth = context.subscriber_growth(start_age - CONFIRM_BEFORE, end_age + CONFIRM_AFTER)
    if growth is not None and growth >= SUBSCRIBER_GROWTH:
        return True
    shares, views = prepared.metrics.get(Metric.SHARES), prepared.metrics.get(Metric.VIEWS)
    if shares is None or views is None:
        return False
    before = float(np.interp(start_age, shares.ages, shares.values))
    delta = float(np.interp(end_age + CONFIRM_AFTER, shares.ages, shares.values)) - before
    # Репосты за волну выросли хотя бы на треть — пост разошёлся по стенам.
    return delta >= max(5.0, 0.33 * before)
