"""Линейная подача: почти постоянная скорость там, где органика обязана затухать.

Кандидаты — участки, где скользящее окно из нескольких ячеек почти не меняет
скорость; границы уточняются PELT на корне из приростов (для пуассоновского
счётчика это выравнивает разброс). Признак — только если участок начался
ступенькой вверх от затухшего фона или днём оборвался: ровный органический
хвост (RuTube, крупный канал) ни того ни другого не имеет.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from ..domain import Family, Metric, Sign
from ..series import HOUR, PreparedSeries
from .base import DetectorContext, age_text, expected_step, make_sign, number, pelt, scale_text, strongest

ID = "linear_feed"
VERSION = "2.4.0"
PATTERN = 1
FAMILY = Family.VELOCITY
NEEDS_NORM = False

SCALES = (timedelta(hours=1), timedelta(hours=6))
METRICS = (Metric.VIEWS, Metric.REACTIONS)
# SMM-панели продают «плавную подачу» на часы и сутки; короче четырёх часов
# ровный участок не отличить от случайного затишья.
MIN_DURATION = 4 * HOUR
# Раньше шести часов органика сама падает круто — сравнивать не с чем.
MIN_ONSET_AGE = 6 * HOUR
# Разброс скорости на участке: пуассоновский шум при сотнях в час даёт
# CV около 0.05, органический хвост с суточным ритмом — 0.3 и больше.
MAX_CV = 0.25
# Скорость в конце и в начале участка отличается не больше чем в 1.4 раза —
# у органики за несколько часов после суток она падает заметнее.
MAX_DRIFT = 1.4
# Участок начинается ступенькой: скорость втрое выше фона шести часов до него.
STEP_UP = 3.0
BACKGROUND_WINDOW = 6 * HOUR
# Фон берётся только из дневных часов: ночью аудитория спит, и утреннее
# оживление поста — суточный ритм, а не ступенька подачи. Пока пустые ночные
# часы считались пробелом, фона не было и признак не выставлялся; с журналом
# сбора они видны, и без этого правила каждое утро давало бы «подачу».
NIGHT_HOURS_MSK = range(0, 7)
BACKGROUND_LOOKBACK = 18 * HOUR
# Или участок кончается обрывом: средняя скорость двух ячеек сразу за ним
# (не дальше четырёх часов: соседние ячейки бывают на пробеле) ниже в пять раз.
STEP_DOWN = 5.0
# Обрыв засчитывается только днём: вечером и ночью приток падает и у живого
# поста (суточный ритм).
DAY_HOURS_MSK = range(8, 20)
# ВК через сутки убирает пост из ленты, и просмотры у любого поста падают
# с десятков в час до единиц (spb1724, ivgpu, theacademy и ещё шесть
# аккаунтов — ровно на 24-м часе): такой обрыв — граница ленты, не подачи.
FEED_LIMIT = {"vk": (22 * HOUR, 26 * HOUR)}
AFTER_CELLS = 2
AFTER_WINDOW = 4 * HOUR
MSK_OFFSET = 3 * HOUR
# Незначимый по объёму участок не признак: минимум 20 % значения на начало.
MIN_SHARE = 0.2
MIN_DELTA = {Metric.VIEWS: 100, Metric.REACTIONS: 30}
NAMES = {Metric.VIEWS: "просмотры", Metric.REACTIONS: "реакции"}

# Короткая подача реакций: ровный темп на пятнадцатиминутках от часа, затем
# обрыв. Живой отклик в первые часы затухает — больше всего реакций в первые
# минуты. СКФУ в MAX: ~42 реакции в час каждую четверть часа (разброс 3–10 %)
# полтора часа, затем 1–3 в час. На 24 тыс. постах 12.09–05.10 — 150 постов
# MAX (102 СКФУ, 47 Губкинский, один другой) и 38 ВК (34 у пяти аккаунтов).
SHORT_SCALE = timedelta(minutes=15)
# От 75 минут: ровный час с пятикратным спадом после бывает и у живого поста.
SHORT_MIN_CELLS, SHORT_MAX_CELLS = 5, 16
SHORT_ONSET_UNTIL = 12 * HOUR
SHORT_MIN_TOTAL = 30.0
SHORT_KEEP = 0.7            # последняя треть участка — не ниже 70 % первой
SHORT_STOP = 5.0            # следующий час — впятеро медленнее
SHORT_CONFIRMED_STOP = 10.0 # для подтверждённой подачи — вдесятеро
SHORT_AFTER_CELLS = 4
# Разброс скорости по пятнадцатиминуткам: до 20 % — подтверждённая подача
# (уровень 3 сам по себе), до 35 % — выраженная. Разброс 40 % и темп 20–28 в
# час дают и синтетические живые посты ВК — это не признак.
SHORT_LEVELS = ((0.2, 0.95), (0.35, 0.75))
# Медленнее 30 в час ровный темп бывает и у живого поста (три поста Telegram
# разных аккаунтов на выборке, ~20/ч).
SHORT_MIN_RATE = 30.0
STEADY_STOP_MODE = "steady_feed_stop_v1"


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    signs: list[Sign] = []
    for metric in METRICS:
        data = prepared.metrics.get(metric)
        if data is None or data.source_counter:
            continue
        for scale in SCALES:
            grid = data.grids.get(scale)
            if grid is not None and grid.rates.size:
                signs.extend(_scan(prepared, context, metric, data, grid))
    short = _short_reactions(prepared)
    if short is not None:
        signs.append(short)
    return tuple(strongest(signs))


def _short_reactions(prepared: PreparedSeries) -> Sign | None:
    data = prepared.metrics.get(Metric.REACTIONS)
    grid = None if data is None else data.grids.get(SHORT_SCALE)
    if grid is None or not grid.rates.size:
        return None
    width = SHORT_SCALE.total_seconds()
    rates = grid.rates * HOUR
    starts = grid.edges[:-1]
    valid = grid.usable & ~grid.negative & (expected_step(prepared, starts) <= width)
    # Все окна сразу на префиксных суммах: детектор укладывается в бюджет
    # анализа поста. Выбирается самое длинное окно, при равной длине — раннее.
    total = np.concatenate(([0.0], np.cumsum(rates)))
    squares = np.concatenate(([0.0], np.cumsum(rates ** 2)))
    usable = np.concatenate(([0], np.cumsum(~valid)))
    onsets = np.flatnonzero(starts <= SHORT_ONSET_UNTIL)
    best = None
    for cells in range(SHORT_MIN_CELLS, SHORT_MAX_CELLS + 1):
        begin = onsets[onsets + cells + SHORT_AFTER_CELLS <= rates.size]
        if not begin.size:
            break
        end = begin + cells
        mean = (total[end] - total[begin]) / cells
        spread = np.sqrt(np.maximum((squares[end] - squares[begin]) / cells - mean ** 2, 0.0))
        third = max(1, cells // 3)
        first = (total[begin + third] - total[begin]) / third
        last = (total[end] - total[end - third]) / third
        after = (total[end + SHORT_AFTER_CELLS] - total[end]) / SHORT_AFTER_CELLS
        with np.errstate(divide="ignore", invalid="ignore"):
            drift = last / np.maximum(first, 1e-9)
            cv = np.where(mean > 0, spread / np.maximum(mean, 1e-9), np.inf)
        ok = ((usable[end + SHORT_AFTER_CELLS] == usable[begin]) & (mean >= SHORT_MIN_RATE)
              & (mean * cells * width / HOUR >= SHORT_MIN_TOTAL) & (drift >= SHORT_KEEP) & (drift <= 1 / SHORT_KEEP)
              & (cv <= SHORT_LEVELS[-1][0]) & (after * SHORT_STOP <= mean))
        hit = np.flatnonzero(ok)
        if hit.size:
            k = int(hit[0])
            best = (int(begin[k]), cells, float(mean[k]), float(after[k]), float(cv[k]))
    if best is None:
        return None
    begin, cells, mean, after, cv = best
    end = begin + cells
    strength = next(value for limit, value in SHORT_LEVELS if cv <= limit)
    if after * SHORT_CONFIRMED_STOP > mean:
        strength = min(strength, SHORT_LEVELS[-1][1])
    start_age, end_age = float(grid.edges[begin]), float(grid.edges[end])
    formula = (f"реакции ≈ {number(mean)}/ч ровно {age_text(end_age - start_age)} "
               f"(t ∈ [{age_text(start_age)}; {age_text(end_age)}], разброс по 15 мин — {cv:.0%}); "
               f"затем {number(after)}/ч. Живой отклик в первые часы затухает, а не идёт ровно и не обрывается")
    render = {"kind": "linear", "slope": round(mean, 3), "intercept": round(float(grid.cumulative[begin]), 1),
              "cv": round(cv, 3), "afterRate": round(after, 3), "stepDown": True, "mode": "short_reactions"}
    if strength >= 0.9:
        render["plateauEvidence"] = STEADY_STOP_MODE
    return make_sign(PATTERN, FAMILY, prepared, Metric.REACTIONS, strength, start_age, end_age, SHORT_SCALE,
                     formula, render, ("reaction_counter_batch_update",))


def _scan(prepared, context, metric, data, grid):
    width = grid.scale.total_seconds()
    starts = grid.edges[:-1]
    steps = expected_step(prepared, starts)
    # Ячейка мельче шага сбора — интерполяция между двумя замерами, её
    # «ровность» ничего не говорит о подаче.
    observed = grid.usable & ~grid.negative & (steps <= width)
    valid = observed & (grid.rates > 0)
    rates = grid.rates * HOUR
    window = max(3, int(np.ceil(MIN_DURATION / width)))
    if rates.size < window:
        return []
    views = np.lib.stride_tricks.sliding_window_view(rates, window)
    ok = np.lib.stride_tricks.sliding_window_view(valid, window).all(axis=1)
    means = views.mean(axis=1)
    cv = np.divide(views.std(axis=1), means, out=np.full(means.size, np.inf), where=means > 0)
    flat = ok & (cv <= MAX_CV)
    signs = []
    index = 0
    while index < flat.size:
        if not flat[index]:
            index += 1
            continue
        first, level = index, means[index]
        while index + 1 < flat.size and flat[index + 1] and abs(means[index + 1] / level - 1) <= 0.3:
            index += 1
        begin, end = _refine(rates, valid, first, index + window)
        sign = _judge(prepared, metric, data, grid, rates, observed, begin, end)
        if sign is not None:
            signs.append(sign)
        index += 1
    return signs


def _refine(rates: np.ndarray, valid: np.ndarray, begin: int, end: int) -> tuple[int, int]:
    margin = end - begin
    low, high = max(0, begin - margin), min(rates.size, end + margin)
    segment = np.sqrt(np.maximum(rates[low:high], 0))
    if segment.size < 4 or not valid[low:high].all():
        return begin, end
    noise = np.median(np.abs(np.diff(segment))) / 0.6745 / np.sqrt(2)
    penalty = 3 * np.log(segment.size) * max(noise, 0.5) ** 2
    bounds = pelt(segment, penalty)
    best = max(zip(bounds, bounds[1:]),
               key=lambda item: min(item[1] + low, end) - max(item[0] + low, begin))
    left, right = best[0] + low, best[1] + low
    return (left, right) if right - left >= 2 else (begin, end)


def _daytime_background(prepared, grid, rates, valid, begin) -> np.ndarray:
    """Скорости дневных пригодных ячеек до участка: не больше шести часов, не дальше 18."""
    width = grid.scale.total_seconds()
    wanted = max(1, int(BACKGROUND_WINDOW / width))
    earliest = max(0, begin - max(1, int(BACKGROUND_LOOKBACK / width)))
    published = prepared.series.published_at.timestamp()
    picked: list[float] = []
    for cell in range(begin - 1, earliest - 1, -1):
        clock = int((published + grid.edges[cell] + MSK_OFFSET) // HOUR) % 24
        if valid[cell] and clock not in NIGHT_HOURS_MSK:
            picked.append(float(rates[cell]))
            if len(picked) >= wanted:
                break
    return np.asarray(picked)


def _after(prepared, grid, rates, valid, end) -> np.ndarray:
    """Скорости первых пригодных дневных ячеек сразу за участком (не дальше AFTER_WINDOW)."""
    width = grid.scale.total_seconds()
    published = prepared.series.published_at.timestamp()
    stop = min(rates.size, end + max(AFTER_CELLS, int(AFTER_WINDOW / width)))
    cells = []
    for cell in range(end, stop):
        clock = int((published + grid.edges[cell] + MSK_OFFSET) // HOUR) % 24
        if not valid[cell]:
            continue
        if clock not in DAY_HOURS_MSK:
            return np.zeros(0)
        cells.append(float(rates[cell]))
    return np.asarray(cells[:AFTER_CELLS])


def _judge(prepared, metric, data, grid, rates, valid, begin, end):
    width = grid.scale.total_seconds()
    start_age, end_age = float(grid.edges[begin]), float(grid.edges[end])
    duration = end_age - start_age
    segment = rates[begin:end]
    if duration < MIN_DURATION or start_age < MIN_ONSET_AGE or not valid[begin:end].all():
        return None
    mean = float(segment.mean())
    cv = float(segment.std() / mean) if mean > 0 else np.inf
    third = max(1, segment.size // 3)
    drift = float(segment[-third:].mean() / max(segment[:third].mean(), 1e-9))
    background = _daytime_background(prepared, grid, rates, valid, begin)
    if cv > MAX_CV or not 1 / MAX_DRIFT <= drift <= MAX_DRIFT:
        return None
    stepped_up = background.size and max(float(np.median(background)), 1.0) * STEP_UP <= mean
    # Обрыв подачи: сразу за ровным участком скорость падает в пять раз и
    # больше. Органика затухает плавно; ровные 62 просмотра в час всю ночь и
    # затем +9 за два часа (Губкинский в MAX, 23–25.09) — нет. Начало такой
    # подачи ступенькой не выделяется: первые часы поста и так быстрые.
    after = _after(prepared, grid, rates, valid, end)
    feed_limit = FEED_LIMIT.get(prepared.series.platform)
    at_feed_limit = feed_limit is not None and feed_limit[0] <= end_age <= feed_limit[1]
    stepped_down = (after.size >= AFTER_CELLS and not at_feed_limit
                    and mean >= STEP_DOWN * max(float(after.mean()), 1.0))
    if not stepped_up and not stepped_down:
        return None
    start_value = float(grid.cumulative[begin])
    delta = float(grid.cumulative[end] - start_value)
    if delta < max(MIN_DELTA[metric], MIN_SHARE * start_value):
        return None
    hours = (grid.edges[begin:end + 1] - start_age) / HOUR
    slope, intercept = np.polyfit(hours, grid.cumulative[begin:end + 1], 1)
    fitted = slope * hours + intercept
    residual = float(np.sum((grid.cumulative[begin:end + 1] - fitted) ** 2))
    total = float(np.sum((grid.cumulative[begin:end + 1] - grid.cumulative[begin:end + 1].mean()) ** 2))
    r_squared = 1 - residual / total if total > 0 else 1.0
    strength = 0.4 + 0.3 * (1 - cv / MAX_CV) + 0.3 * min(1.0, duration / (12 * HOUR))
    formula = (f"Δ{NAMES[metric]} ≈ {number(slope)}·t (t в часах), R² = {r_squared:.3f}, "
               f"t ∈ [{age_text(start_age)}; {age_text(end_age)}], масштаб {scale_text(grid.scale)}"
               + (f"; затем обрыв до {number(float(after.mean()))}/ч" if stepped_down else ""))
    return make_sign(PATTERN, FAMILY, prepared, metric, strength, start_age, end_age, grid.scale,
                     formula, {"kind": "linear", "slope": round(float(slope), 3),
                               "intercept": round(float(intercept), 1), "r2": round(r_squared, 4),
                               "cv": round(cv, 3),
                               "background": round(float(np.median(background)), 3) if background.size else None,
                               "afterRate": round(float(after.mean()), 3) if after.size else None,
                               "stepDown": bool(stepped_down)},
                     ("recommendation_feed", "smoothed_large_audience"))
