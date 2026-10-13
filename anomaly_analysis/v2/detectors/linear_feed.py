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
from ..series import HOUR, PointFlag, PreparedSeries, growth_bounds
from .base import DetectorContext, age_text, expected_step, make_sign, number, pelt, scale_text, strongest

ID = "linear_feed"
VERSION = "2.6.0"
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
# Найденный участок показывается на весь эпизод: соседние часы с темпом в
# пределах ×1,5 от темпа участка — та же подача. Ровная подача МИСИС в
# Telegram (01.10) шла с 6-го по 40-й час, а признак закрывал 6–12 ч: дальше
# начиналась ночь, и обрыв там не засчитывается, а ступеньки у продолжения нет.
WIDEN_TOLERANCE = 1.5
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

# Короткая подача просмотров с публикации: пакет, заказанный к выходу поста.
# Косыгин в ВК: ~400/ч 2–3 ч с публикации, ~1 000 и обрыв в 25 раз, 2 реакции
# на 1 000 просмотров против 9 у остального поста. Поздняя ветка (начало не
# раньше 6 ч, длительность от 4 ч) такой пакет не видит. Живой приток с первых
# минут затухает; ровный с обрывом бывает и у попадания в рекомендации, но
# тогда реакции идут как у остального поста — поэтому без низкого отклика
# признак не выше слабого сигнала.
VIEW_SHORT_SCALE = timedelta(minutes=15)
VIEW_SHORT_ONSET_UNTIL = 12 * HOUR
# 1,5–10 ч. Калибровка 01–21.09: у Косыгина в ВК часть пакетов длится 1 ч 45 мин;
# порог 1,5 ч добавил пять срабатываний, все в аккаунтах с пакетами, ни одного
# у других аккаунтов.
VIEW_SHORT_CELLS = (6, 40)
VIEW_SHORT_MIN_RATE = 150.0            # просмотров в час
VIEW_SHORT_BACKGROUND = 3.0            # темп не ниже трёх фонов
VIEW_SHORT_SPREAD = 2.0                # часовые темпы в пределах ×2
VIEW_SHORT_MAX_CV = 0.35
VIEW_SHORT_STOP = 5.0
VIEW_SHORT_HARD_STOP = 10.0
VIEW_SHORT_AFTER = 2 * HOUR
VIEW_SHORT_RESPONSE = 1 / 3            # реакций на просмотр в пакете ≤ трети остального поста
VIEW_SHORT_SILENT_PER_K = 1.0
VIEW_SHORT_MIN_REST_REACTIONS = 10
# Пробел опроса внутри участка — не больше четверти его ячеек: сумма участка
# известна по краям (Косыгин 22.09: полчаса без замеров внутри трёхчасового
# пакета). Начало участка и окно после обрыва должны быть покрыты целиком.
VIEW_SHORT_MAX_GAP_SHARE = 0.25
# Ячейка пригодна, если её покрывают замеры не дальше 45 минут друг от друга:
# сумма за час известна и при опросе раз в 20–30 минут (Косыгин в ВК), хотя
# «ожидаемый шаг» первых суток — 5 минут, и общая сетка такие ячейки отбрасывает.
VIEW_SHORT_MAX_SPACING = 45 * 60
VIEW_SHORT_EXPLICIT, VIEW_SHORT_PRONOUNCED = 0.95, 0.75


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    signs: list[Sign] = []
    for metric in METRICS:
        data = prepared.metrics.get(metric)
        # Просмотры Telegram с тысячи показаны «1,2K»: точных точек там нет,
        # ряд берётся с коридором показа, а условия — по худшему случаю.
        bounded = prepared.bounded_views if metric is Metric.VIEWS else None
        if bounded is not None:
            data = bounded.data
        if data is None or data.source_counter:
            continue
        for scale in SCALES:
            grid = data.grids.get(scale)
            if grid is not None and grid.rates.size:
                signs.extend(_scan(prepared, context, metric, data, grid, bounded))
    short = _short_reactions(prepared)
    if short is not None:
        signs.append(short)
    pack = _short_views(prepared)
    if pack is not None:
        signs.append(pack)
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


def _short_views(prepared: PreparedSeries) -> Sign | None:
    bounded = prepared.bounded_views
    data = bounded.data if bounded is not None else prepared.metrics.get(Metric.VIEWS)
    if data is None or data.source_counter:
        return None
    grid = data.grids.get(VIEW_SHORT_SCALE)
    width = VIEW_SHORT_SCALE.total_seconds()
    after_cells = int(VIEW_SHORT_AFTER / width)
    # Замеры реже VIEW_SHORT_MAX_SPACING (RuTube — раз в час): формы участка не видно.
    early = data.ages[data.ages <= VIEW_SHORT_ONSET_UNTIL + VIEW_SHORT_CELLS[1] * VIEW_SHORT_SCALE.total_seconds()]
    if early.size < 2 or float(np.median(np.diff(early))) > VIEW_SHORT_MAX_SPACING:
        return None
    # Первые часы поста не прочитаны — пакета с публикации не видно.
    if (grid is None or grid.rates.size < VIEW_SHORT_CELLS[0] + after_cells
            or grid.edges[0] > VIEW_SHORT_ONSET_UNTIL):
        return None
    # Пакет начинается не позже VIEW_SHORT_ONSET_UNTIL и длится не дольше
    # VIEW_SHORT_CELLS[1]: дальше первых суток сетку читать незачем.
    size = min(grid.rates.size, int((VIEW_SHORT_ONSET_UNTIL - grid.edges[0]) // width) + 1
               + VIEW_SHORT_CELLS[1] + after_cells)
    rates = grid.rates[:size] * HOUR
    # Быстрый отсев: ни одного отрезка в полтора часа со средним темпом пакета.
    shortest = VIEW_SHORT_CELLS[0]
    if size < shortest or (np.convolve(rates, np.ones(shortest), "valid") / shortest).max() < VIEW_SHORT_MIN_RATE:
        return None
    edges = grid.edges[:size + 1]
    starts = edges[:-1]
    valid = ~grid.negative[:size] & _spaced(data.ages, data.flags, edges)
    # Первый час ровного участка не медленнее половины среднего темпа (часовые
    # темпы в пределах ×2; у участка из 6–7 ячеек то же следует из разброса):
    # начала с первым часом медленнее VIEW_SHORT_MIN_RATE / 2 не перебираются.
    head = np.convolve(rates, np.ones(4), "valid") / 4
    begins = np.flatnonzero(starts[:head.size] <= VIEW_SHORT_ONSET_UNTIL)
    begins = begins[head[begins] >= VIEW_SHORT_MIN_RATE / VIEW_SHORT_SPREAD]
    if not begins.size:
        return None
    # Все пары (начало, длина) сразу на префиксных суммах: детектор укладывается
    # в бюджет анализа поста. Выбирается самое раннее начало, при нём — самый
    # длинный участок.
    lengths = np.arange(VIEW_SHORT_CELLS[0], VIEW_SHORT_CELLS[1] + 1)
    total = np.concatenate(([0.0], np.cumsum(rates)))
    squares = np.concatenate(([0.0], np.cumsum(rates ** 2)))
    bad = np.concatenate(([0], np.cumsum(~valid)))
    ends = begins[:, None] + lengths[None, :]
    inside = ends + after_cells <= size
    ends_at = np.minimum(ends, size - after_cells)
    first = begins[:, None]
    mean = (total[ends_at] - total[first]) / lengths
    spread = np.sqrt(np.maximum((squares[ends_at] - squares[first]) / lengths - mean ** 2, 0.0))
    after = (total[ends_at + after_cells] - total[ends_at]) / after_cells
    # Часовые темпы участка: суммы по четыре ячейки с шагом в час от начала.
    hours = lengths // 4
    block = np.concatenate((total[4:] - total[:-4], np.zeros(4)))
    picks = np.minimum(begins[:, None] + 4 * np.arange(hours.max())[None, :], block.size - 1)
    blocks = block[picks]
    low = np.minimum.accumulate(blocks, axis=1)[:, hours - 1]
    high = np.maximum.accumulate(blocks, axis=1)[:, hours - 1]
    end_ages = grid.edges[ends_at]
    published = prepared.series.published_at.timestamp()
    clock = ((published + end_ages + MSK_OFFSET) // HOUR).astype(np.int64) % 24
    daytime = np.isin(clock, np.fromiter(DAY_HOURS_MSK, dtype=np.int64))
    feed_limit = FEED_LIMIT.get(prepared.series.platform)
    at_limit = (np.zeros_like(daytime) if feed_limit is None
                else (feed_limit[0] <= end_ages) & (end_ages <= feed_limit[1]))
    background = np.where(begins >= 4, (total[begins] - total[np.maximum(begins - 4, 0)]) / 4, np.nan)
    background = np.where(np.isnan(background)[:, None], after, background[:, None])
    gaps_inside = bad[ends_at] - bad[first]
    covered = ((gaps_inside <= np.floor(VIEW_SHORT_MAX_GAP_SHARE * lengths)) & valid[begins][:, None]
               & (bad[ends_at + after_cells] == bad[ends_at]))
    ok = (inside & covered & (mean >= VIEW_SHORT_MIN_RATE)
          & (spread <= VIEW_SHORT_MAX_CV * mean) & (low * VIEW_SHORT_SPREAD >= high)
          # Участок кончается там, где обрыв: первая ячейка за ним уже медленная.
          # Иначе хвост пакета попадает в окно «после», а конец — раньше
          # настоящего, и граница ленты ВК не узнаётся.
          & (rates[ends_at] * VIEW_SHORT_STOP <= mean) & (after * VIEW_SHORT_STOP <= mean)
          & daytime & ~at_limit & (mean >= VIEW_SHORT_BACKGROUND * np.maximum(background, 1.0)))
    rows = np.flatnonzero(ok.any(axis=1))
    if not rows.size:
        return None
    row = int(rows[0])
    column = int(np.flatnonzero(ok[row])[-1])
    begin, end = int(begins[row]), int(ends[row, column])
    return _pack_sign(prepared, grid, bounded, begin, end, float(mean[row, column]), float(after[row, column]),
                      float(data.values[-1]))


def _spaced(ages: np.ndarray, flags: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Ячейки, которые покрывают замеры не дальше VIEW_SHORT_MAX_SPACING друг от друга.

    Сброс счётчика и пропуск метрики в замере делают отрезок непригодным.
    """
    if ages.size < 2:
        return np.zeros(edges.size - 1, dtype=bool)
    spacing = np.diff(ages)
    broken = (flags[1:] & np.uint8(PointFlag.COUNTER_RESET | PointFlag.MISSING)) != 0
    bad = (spacing > VIEW_SHORT_MAX_SPACING) | broken
    last = ages.size - 2
    first = np.clip(np.searchsorted(ages, edges[:-1], side="right") - 1, 0, last)
    stop = np.clip(np.searchsorted(ages, edges[1:], side="left"), 1, last + 1)
    prefix = np.concatenate(([0], np.cumsum(bad)))
    inside = (edges[:-1] >= ages[0]) & (edges[1:] <= ages[-1])
    return inside & (prefix[stop] - prefix[first] == 0)


def _reactions_at(data, age: float) -> float | None:
    """Реакции на возрасте: замер или интерполяция между замерами не дальше VIEW_SHORT_MAX_SPACING."""
    if data is None or not data.ages.size or not data.ages[0] <= age <= data.ages[-1]:
        return None
    right = int(np.searchsorted(data.ages, age))
    if data.ages[right] == age:
        return float(data.values[right])
    if data.ages[right] - data.ages[right - 1] > VIEW_SHORT_MAX_SPACING or data.flags[right] & np.uint8(
            PointFlag.COUNTER_RESET | PointFlag.MISSING):
        return None
    return float(np.interp(age, data.ages[right - 1:right + 1], data.values[right - 1:right + 1]))


def _pack_sign(prepared, grid, bounded, begin, end, mean, after, v_last) -> Sign | None:
    start_age, end_age = float(grid.edges[begin]), float(grid.edges[end])
    duration = end_age - start_age
    mode = None
    views = float(grid.cumulative[end] - grid.cumulative[begin])
    if bounded is not None:
        pack = growth_bounds(bounded, start_age, end_age)
        tail = growth_bounds(bounded, end_age, end_age + VIEW_SHORT_AFTER)
        if pack is None or tail is None:
            return None
        views = pack[0]
        mean, after = views / duration * HOUR, tail[1] / VIEW_SHORT_AFTER * HOUR
        if mean < VIEW_SHORT_MIN_RATE or after * VIEW_SHORT_STOP > mean:
            return None
        mode = "bounded_views"
    reactions = prepared.metrics.get(Metric.REACTIONS)
    last_age = float(reactions.ages[-1]) if reactions is not None and reactions.ages.size else end_age
    r_start, r_end, r_last = (_reactions_at(reactions, age) for age in (start_age, end_age, last_age))
    # Признак — только при проверенном низком отклике в участке. Ровный приток с
    # обрывом при обычном отклике (рекомендации) или без реакций для сравнения
    # свидетельством не считается: на карточках 22.09–07.10 такие слабые
    # сигналы в четырёх случаях из девяти ложились на живые посты.
    if None in (r_start, r_end, r_last):
        return None
    pack_reactions = max(0.0, r_end - r_start)
    rest_reactions = max(0.0, r_last - pack_reactions)
    pack_per_k = 1000 * pack_reactions / max(views, 1.0)
    rest_per_k = 1000 * rest_reactions / max(1.0, v_last - views)
    if rest_reactions < VIEW_SHORT_MIN_REST_REACTIONS or pack_per_k > VIEW_SHORT_RESPONSE * rest_per_k:
        return None
    strength = (VIEW_SHORT_EXPLICIT if after * VIEW_SHORT_HARD_STOP <= mean or pack_per_k <= VIEW_SHORT_SILENT_PER_K
                else VIEW_SHORT_PRONOUNCED)
    alternatives = ("paid_promotion", "site_embed", "mailing_link")
    formula = (f"просмотры: +{number(views)} за {age_text(duration)} ровным темпом ≈ {number(mean)}/ч "
               f"(t ∈ [{age_text(start_age)}; {age_text(end_age)}]), затем {number(after)}/ч")
    formula += (f"; реакций на 1 000 просмотров в участке — {pack_per_k:.1f}, "
                f"у остального поста — {rest_per_k:.1f}")
    formula += ". Живой приток в первые часы затухает, а не идёт ровно и не обрывается"
    render = {"kind": "linear", "mode": "short_views", "stepDown": True, "packViews": round(views),
              "slope": round(mean, 3), "intercept": round(float(grid.cumulative[begin]), 1),
              "afterRate": round(after, 3),
              "packReactionsPerK": round(pack_per_k, 2), "restReactionsPerK": round(rest_per_k, 2)}
    if mode:
        render["measurementMode"] = mode
    return make_sign(PATTERN, FAMILY, prepared, Metric.VIEWS, strength, start_age, end_age, VIEW_SHORT_SCALE,
                     formula, render, alternatives)


def _scan(prepared, context, metric, data, grid, bounded=None):
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
        sign = _judge(prepared, metric, data, grid, rates, observed, begin, end, bounded)
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
    return np.asarray([float(rates[cell]) for cell in _daytime_cells(prepared, grid, valid, begin)])


def _daytime_cells(prepared, grid, valid, begin) -> list[int]:
    """Номера ячеек фона: дневные пригодные до участка, не больше шести часов, не дальше 18."""
    width = grid.scale.total_seconds()
    wanted = max(1, int(BACKGROUND_WINDOW / width))
    earliest = max(0, begin - max(1, int(BACKGROUND_LOOKBACK / width)))
    published = prepared.series.published_at.timestamp()
    picked: list[int] = []
    for cell in range(begin - 1, earliest - 1, -1):
        clock = int((published + grid.edges[cell] + MSK_OFFSET) // HOUR) % 24
        if valid[cell] and clock not in NIGHT_HOURS_MSK:
            picked.append(cell)
            if len(picked) >= wanted:
                break
    return picked


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


def _widen(rates: np.ndarray, valid: np.ndarray, begin: int, end: int, mean: float) -> tuple[int, int]:
    """Расширить участок на соседние пригодные ячейки с темпом в пределах ×WIDEN_TOLERANCE."""
    low, high = mean / WIDEN_TOLERANCE, mean * WIDEN_TOLERANCE
    while begin > 0 and valid[begin - 1] and low <= rates[begin - 1] <= high:
        begin -= 1
    while end < rates.size and valid[end] and low <= rates[end] <= high:
        end += 1
    return begin, end


def _bounded_check(bounded, start_age, end_age, duration, width, stepped_up, stepped_down,
                   background_cells=()):
    """Ступенька и обрыв по худшему случаю внутри коридоров «1,2K».

    Прирост участка — наименьший возможный, фон и хвост — наибольшие. Фон —
    те же дневные ячейки перед участком, что и у точных счётчиков, каждая по
    наибольшему возможному приросту, и их медиана. Среднее за шесть часов до
    участка захватывало крутой старт поста: подача с 6-го часа (МИСИС, 01.10)
    ступенькой не признавалась. None — при любых значениях в коридорах ни
    ступеньки, ни обрыва нет.
    """
    growth = growth_bounds(bounded, start_age, end_age)
    if growth is None:
        return None
    delta = growth[0]
    mean = delta / duration * HOUR
    if stepped_down:
        tail = growth_bounds(bounded, end_age, end_age + AFTER_CELLS * width)
        stepped_down = tail is not None and mean >= STEP_DOWN * max(tail[1] / (AFTER_CELLS * width) * HOUR, 1.0)
    if stepped_up:
        uppers = [growth_bounds(bounded, cell_start, cell_start + width) for cell_start in background_cells]
        stepped_up = bool(uppers) and all(item is not None for item in uppers) and mean >= STEP_UP * max(
            float(np.median([item[1] for item in uppers])) / width * HOUR, 1.0)
    if not stepped_up and not stepped_down:
        return None
    return delta, stepped_up, stepped_down


def _judge(prepared, metric, data, grid, rates, valid, begin, end, bounded=None):
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
    background_cells = _daytime_cells(prepared, grid, valid, begin)
    background = np.asarray([float(rates[cell]) for cell in background_cells])
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
    mode = None
    if bounded is not None:
        verdict = _bounded_check(bounded, start_age, end_age, duration, width, stepped_up, stepped_down,
                                 [float(grid.edges[cell]) for cell in background_cells])
        if verdict is None:
            return None
        delta, stepped_up, stepped_down = verdict
        mode = "bounded_views"
    if delta < max(MIN_DELTA[metric], MIN_SHARE * start_value):
        return None
    # Участок доказан; показывается он на весь эпизод той же подачи.
    core = (begin, end)
    begin, end = _widen(rates, valid, begin, end, mean)
    if (begin, end) != core:
        start_age, end_age = float(grid.edges[begin]), float(grid.edges[end])
        duration = end_age - start_age
        start_value = float(grid.cumulative[begin])
        delta = float(grid.cumulative[end] - start_value)
        if bounded is not None:
            widened = growth_bounds(bounded, start_age, end_age)
            delta = widened[0] if widened is not None else delta
        if not stepped_down:
            after = _after(prepared, grid, rates, valid, end)
            at_feed_limit = feed_limit is not None and feed_limit[0] <= end_age <= feed_limit[1]
            stepped_down = (after.size >= AFTER_CELLS and not at_feed_limit
                            and mean >= STEP_DOWN * max(float(after.mean()), 1.0))
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
                               "stepDown": bool(stepped_down),
                               **({"measurementMode": mode} if mode else {})},
                     ("recommendation_feed", "smoothed_large_audience"))
