"""Эпизод отклика: доля реакций на новый просмотр резко меняет режим.

Живая аудитория реагирует с долей, которая меняется плавно: в первые часы
пост видят подписчики, позже — случайные читатели, и доля реакций на
просмотр постепенно снижается (ADR-015: за 4–14 суток примерно вшестеро).
Доставленная пачка реакций выглядит иначе: на каком-то отрезке реакций
приходится по 30–90 на сотню новых просмотров, а сразу после него — почти
ноль, хотя просмотры продолжают прибывать. Бывает и обратное: реакций
почти нет, а потом они «включаются» без новой аудитории.

Ряд делится на отрезки с постоянной долей q (PELT с пуассоновской
стоимостью: ΔR ~ Poisson(q·ΔV) на каждом интервале между замерами). Эпизод —
отрезок с наибольшей долей вместе с примыкающими отрезками не ниже трети
её. Нулевая гипотеза щедра к органике: в соседнем окне доля могла упасть
вчетверо (за 24 часа — в восемь раз). Признак — когда реакций в соседнем
окне столько, что при такой гипотезе это почти невозможно, и доли
отличаются хотя бы в восемь раз. Сравниваются только точные концы окон;
форма прироста между замерами не утверждается.

Детектору не нужны ни норма, ни история аккаунта: пост сравнивается сам с
собой, поэтому повторяющаяся подача не превращается в «норму канала».
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import math

import numpy as np
from scipy.stats import poisson

from ..domain import Family, Metric, Sign
from ..series import HOUR, PointFlag, PreparedSeries
from .base import DetectorContext, age_text, make_sign, number

ID = "engagement_regime"
VERSION = "1.0.0"
PATTERN = 14
FAMILY = Family.CROSS_METRIC
NEEDS_NORM = False
MEASUREMENT_MODE = "engagement_regime_v1"

# Интервал короче пяти новых просмотров — шум округления; он сливается со
# следующим, чтобы доля считалась по осмысленному знаменателю.
MIN_INTERVAL_VIEWS = 5
# Счётчики MAX и ВК обновляются пакетами (base.COUNTER_DELAY_SECONDS):
# пятиминутные интервалы мельче точности, на которой судится доля.
MIN_INTERVAL_SECONDS = 15 * 60
# Штраф PELT за лишнюю границу отрезка в единицах −log L: граница должна
# объяснять данные заметно лучше, чем одна общая доля.
PENALTY = 12.0
# Отрезки эпизода — не ниже трети доли пика: пачка часто нарастает.
EPISODE_SHARE = 1 / 3
# Соседние окна и допустимое органическое снижение доли в них.
WINDOWS = ((6 * HOUR, 4.0), (12 * HOUR, 4.0), (24 * HOUR, 8.0))
MIN_WINDOW_SPAN = 2 * HOUR
MIN_WINDOW_VIEWS = 20
MIN_RATIO = 8.0
START_ALLOWANCE = 3.0
MIN_EVENTS = 5
MIN_REACTIONS = 15
# Пачка доставляется за часы, а не за дни. Многодневный «эпизод» на ВК —
# это почти замёрзший счётчик просмотров старого поста, а не доля реакций.
MAX_EPISODE = 24 * HOUR
# −log10 p: от 4 — слабый сигнал; средний, сильный и подтверждённый — по
# таблице ниже. Подтверждённый эпизод один даёт уровень 3: пачка, которая
# обрывается на фоне продолжающихся просмотров, не нуждается во втором методе.
MIN_SURPRISE = 4.0
MEDIUM = (6.0, 8.0)            # surprise, ratio → слабый сигнал средней силы
STRONG = (10.0, 15.0)          # surprise, ratio → выраженная аномалия
CONFIRMED = (12.0, 20.0)       # surprise, ratio → признаки искусственной активности
# Окно, где просмотры прибывали втрое быстрее, чем в эпизоде, — приток
# просмотров без отклика: формулировка называет именно его.
VIEWS_SURGE = 3.0
CONFIRMED_MODE = "confirmed_episode_v1"


@dataclass(frozen=True, slots=True)
class Episode:
    kind: str            # stop | start
    start_age: float
    end_age: float
    reactions: float
    views: float
    window_start: float
    window_end: float
    window_reactions: float
    window_views: float
    ratio: float
    surprise: float

    @property
    def share(self) -> float:
        return self.reactions / max(self.views, 1.0)

    @property
    def window_share(self) -> float:
        return self.window_reactions / max(self.window_views, 1.0)


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    ages, reactions, views = paired(prepared)
    episodes: list[Episode] = []
    for chunk in _chunks(ages, reactions, views):
        episodes.extend(find_episodes(*chunk, delay=context.counter_delay))
    return tuple(_sign(prepared, item) for item in _strongest(episodes))


def paired(prepared: PreparedSeries) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Замеры, где обе метрики точные и получены; сброс счётчика отмечен NaN."""
    r, v = prepared.metrics.get(Metric.REACTIONS), prepared.metrics.get(Metric.VIEWS)
    if r is None or v is None:
        empty = np.zeros(0)
        return empty, empty, empty
    common, ri, vi = np.intersect1d(r.ages, v.ages, assume_unique=True, return_indices=True)
    values_r, values_v = r.values[ri].astype(float), v.values[vi].astype(float)
    # После сброса счётчика реакций доля через границу не считается: это
    # материал детектора списания, а не эпизода.
    reset = (r.flags[ri] & np.uint8(PointFlag.COUNTER_RESET)) != 0
    values_r[reset] = np.nan
    return common, values_r, values_v


def _chunks(ages, reactions, views):
    cut = np.flatnonzero(np.isnan(reactions))
    start = 0
    for index in [*cut, ages.size]:
        stop = index
        if stop - start >= 4:
            yield ages[start:stop], reactions[start:stop], views[start:stop]
        start = index + 1


def find_episodes(ages: np.ndarray, reactions: np.ndarray, views: np.ndarray,
                  delay: float = 0.0) -> list[Episode]:
    intervals = _intervals(ages, reactions, views)
    if len(intervals) < 3:
        return []
    bounds = _pelt(intervals)
    segments = [(intervals[a][0], intervals[b - 1][1], sum(item[2] for item in intervals[a:b]),
                 sum(item[3] for item in intervals[a:b])) for a, b in zip(bounds, bounds[1:])]
    dispersion = _dispersion(intervals, bounds)
    found: list[Episode] = []
    for peak, (_, _, peak_r, peak_v) in enumerate(segments):
        if peak_r < 5 or peak_v <= 0:
            continue
        share = peak_r / peak_v
        first, last = peak, peak
        while first > 0 and _share(segments[first - 1]) >= EPISODE_SHARE * share and segments[first - 1][2] >= 3:
            first -= 1
        while (last + 1 < len(segments) and _share(segments[last + 1]) >= EPISODE_SHARE * share
               and segments[last + 1][2] >= 3):
            last += 1
        start_age, end_age = segments[first][0], segments[last][1]
        total_r = sum(item[2] for item in segments[first:last + 1])
        if total_r < MIN_REACTIONS or end_age - start_age > MAX_EPISODE:
            continue
        # Счётчик просмотров ВК и MAX отстаёт от реакций до получаса: доля
        # эпизода считается по просмотрам, догнавшим его конец.
        caught_up = _window(ages, reactions, views, start_age, end_age + delay)
        total_v = sum(item[3] for item in segments[first:last + 1])
        if caught_up is not None:
            total_v = max(total_v, caught_up[3])
        for kind in ("stop", "start"):
            episode = _test(kind, ages, reactions, views, start_age, end_age, total_r, total_v, dispersion)
            if episode is not None:
                found.append(episode)
    return found


def _dispersion(intervals, bounds) -> float:
    """Квазипуассоновский разброс φ: χ² Пирсона остатков вокруг найденных отрезков.

    Пакетное обновление счётчика даёт приросты крупнее пуассоновских; тест
    тогда делит значимость на φ, а не принимает зернистость за событие.
    """
    chi2, used = 0.0, 0
    for a, b in zip(bounds, bounds[1:]):
        r = sum(item[2] for item in intervals[a:b])
        v = sum(item[3] for item in intervals[a:b])
        if v <= 0:
            continue
        for item in intervals[a:b]:
            expected = r / v * item[3]
            if expected >= 1:
                chi2 += (item[2] - expected) ** 2 / expected
                used += 1
    freedom = used - (len(bounds) - 1)
    # Зернистость: счётчик, который растёт только шагами по k, несёт k-кратный
    # разброс при любом числе интервалов. У живого счётчика наименьший шаг — 1.
    steps = [item[2] for item in intervals if item[2] > 0]
    grain = min(steps) if steps else 1.0
    return max(1.0, grain, chi2 / freedom if freedom >= 5 else 1.0)


def episode_spans(prepared: PreparedSeries, context: DetectorContext) -> list[tuple[float, float]]:
    """Отрезки с повышенной долей реакций без проверки значимости — границы эпизодов.

    Нужны, чтобы признак рывка, найденный на коротком окне, подсвечивал весь
    эпизод: узкая полоса внутри двухчасового пакета вводит в заблуждение.
    """
    spans = []
    for ages, reactions, views in _chunks(*paired(prepared)):
        intervals = _intervals(ages, reactions, views)
        if len(intervals) < 3:
            continue
        bounds = _pelt(intervals)
        segments = [(intervals[a][0], intervals[b - 1][1], sum(item[2] for item in intervals[a:b]),
                     sum(item[3] for item in intervals[a:b])) for a, b in zip(bounds, bounds[1:])]
        total_r = sum(item[2] for item in segments)
        total_v = sum(item[3] for item in segments)
        for start, end, r, v in segments:
            # Отрезок эпизода — доля хотя бы втрое выше, чем на остальном ряду.
            rest = (total_r - r) / max(total_v - v, 1.0)
            if r >= 10 and v > 0 and r / v >= 3 * rest and end - start <= MAX_EPISODE:
                spans.append((start, end))
    return spans


def _share(segment) -> float:
    return segment[2] / segment[3] if segment[3] > 0 else math.inf


def _intervals(ages, reactions, views) -> list[tuple[float, float, float, float]]:
    out = []
    left = 0
    for right in range(1, ages.size):
        if (views[right] - views[left] < MIN_INTERVAL_VIEWS
                or ages[right] - ages[left] < MIN_INTERVAL_SECONDS) and right < ages.size - 1:
            continue
        dr = reactions[right] - reactions[left]
        out.append((float(ages[left]), float(ages[right]), max(float(dr), 0.0),
                    max(float(views[right] - views[left]), 0.0)))
        left = right
    return out


def _pelt(intervals) -> list[int]:
    """Границы отрезков с постоянной долей (Killick и др., 2012, пуассоновская стоимость).

    −log L отрезка при оценке q = R/V без слагаемых, не зависящих от
    разбиения (Σ R_i log V_i, log R_i!): R − R·log(R/V); при R = 0 — ноль.
    """
    n = len(intervals)
    sums_r = np.concatenate(([0.0], np.cumsum([item[2] for item in intervals])))
    sums_v = np.concatenate(([0.0], np.cumsum([item[3] for item in intervals])))
    best = np.zeros(n + 1)
    best[0] = -PENALTY
    previous = np.zeros(n + 1, dtype=np.int64)
    candidates = np.array([0], dtype=np.int64)
    for end in range(1, n + 1):
        r = sums_r[end] - sums_r[candidates]
        v = np.maximum(sums_v[end] - sums_v[candidates], 1e-9)
        safe = np.where(r > 0, r, 1.0)
        cost = np.where(r > 0, r - r * np.log(safe / v), 0.0)
        scores = best[candidates] + cost + PENALTY
        choice = int(np.argmin(scores))
        best[end], previous[end] = scores[choice], candidates[choice]
        candidates = np.append(candidates[scores - PENALTY <= best[end]], end)
    bounds = [n]
    while bounds[-1] > 0:
        bounds.append(int(previous[bounds[-1]]))
    return bounds[::-1]


def _window(ages, reactions, views, start, end):
    inside = np.flatnonzero((ages >= start - 1e-6) & (ages <= end + 1e-6))
    if inside.size < 2:
        return None
    a, b = inside[0], inside[-1]
    return float(ages[a]), float(ages[b]), float(reactions[b] - reactions[a]), float(views[b] - views[a])


def _test(kind, ages, reactions, views, start_age, end_age, total_r, total_v,
          dispersion: float = 1.0) -> Episode | None:
    share = total_r / max(total_v, 1.0)
    # Пять независимых событий — минимум: при зернистом счётчике 30 реакций
    # могут оказаться тремя пакетными обновлениями.
    if total_r / dispersion < MIN_EVENTS:
        return None
    best = None
    for width, decline in WINDOWS:
        span = (end_age, end_age + width) if kind == "stop" else (start_age - width, start_age)
        window = _window(ages, reactions, views, *span)
        if window is None:
            continue
        w0, w1, wr, wv = window
        if w1 - w0 < MIN_WINDOW_SPAN or wv < MIN_WINDOW_VIEWS:
            continue
        wr = max(wr, 0.0)
        floor = max(wr, 0.5 * dispersion) / wv
        if kind == "stop":
            # После эпизода доля могла органически упасть в `decline` раз:
            # сколько реакций окна почти невозможно при таком падении.
            p_value = poisson.cdf(wr / dispersion, share / decline * wv / dispersion)
        else:
            # Органическая доля с возрастом падает, а не растёт. Нулевая гипотеза
            # щедра: в эпизоде доля могла быть втрое выше окна до него.
            p_value = poisson.sf((total_r - 1) / dispersion, START_ALLOWANCE * floor * total_v / dispersion)
        surprise = -math.log10(max(float(p_value), 1e-300))
        ratio = share / floor
        if ratio < MIN_RATIO or surprise < MIN_SURPRISE:
            continue
        if best is None or surprise > best.surprise:
            best = Episode(kind, start_age, end_age, total_r, total_v, w0, w1, wr, wv, ratio, surprise)
    return best


def _strongest(episodes: list[Episode]) -> list[Episode]:
    kept: list[Episode] = []
    # Обе проверки одного эпизода значимы — показывается остановка: её окно
    # «затем» понятнее читателю, чем окно «до этого».
    for item in sorted(episodes, key=lambda x: (-min(x.surprise, CONFIRMED[0]), x.kind != "stop", -x.surprise)):
        if not any(k.start_age < item.end_age and item.start_age < k.end_age for k in kept):
            kept.append(item)
    return kept


def grade(item: Episode) -> tuple[float, bool]:
    """Сила признака и признак подтверждённого эпизода (уровень 3 сам по себе)."""
    if item.surprise >= CONFIRMED[0] and item.ratio >= CONFIRMED[1]:
        return min(0.99, 0.9 + 0.02 * math.log2(item.ratio / CONFIRMED[1] + 1)), True
    if item.surprise >= STRONG[0] and item.ratio >= STRONG[1]:
        return 0.75, False
    if item.surprise >= MEDIUM[0] and item.ratio >= MEDIUM[1]:
        return 0.55, False
    return 0.45, False


def views_surge(item: Episode) -> bool:
    episode_rate = item.views / max(item.end_age - item.start_age, 1.0)
    window_rate = item.window_views / max(item.window_end - item.window_start, 1.0)
    return window_rate >= VIEWS_SURGE * episode_rate


def times(ratio: float) -> str:
    """«в 3 раза», «в 764 раза», «в 12 раз»."""
    value = round(ratio)
    word = "раза" if value % 10 in (2, 3, 4) and value % 100 not in (12, 13, 14) else "раз"
    return f"в {number(value)} {word}"


SUPERSCRIPT = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


def superscript(value: int) -> str:
    return str(value).translate(SUPERSCRIPT)


def _sign(prepared: PreparedSeries, item: Episode) -> Sign:
    strength, confirmed = grade(item)
    duration = age_text(item.end_age - item.start_age)
    window = age_text(item.window_end - item.window_start)
    episode_text = (f"+{number(item.reactions)} реакций при +{number(item.views)} просмотрах за {duration} "
                    f"(t ∈ [{age_text(item.start_age)}; {age_text(item.end_age)}], "
                    f"{item.share:.0%} на просмотр)")
    window_text = (f"+{number(item.window_reactions)} реакций при +{number(item.window_views)} просмотрах "
                   f"за {window} ({item.window_share:.1%})")
    formula = (f"{episode_text}; {'затем' if item.kind == 'stop' else 'до этого'} {window_text} — "
               f"доля {times(item.ratio)} {'ниже' if item.kind == 'stop' else 'ниже, чем в эпизоде'}; "
               f"вероятность при плавном изменении доли ≤ 10{superscript(-round(item.surprise))}")
    # «Приток просмотров» — только когда быстрые просмотры пришли после эпизода и
    # разбавили долю; перед поздним стартом реакций это значило бы обратное.
    surge = item.kind == "stop" and views_surge(item)
    if surge:
        formula += "; в соседнем окне просмотры прибывали заметно быстрее, чем в эпизоде"
    render = {"kind": "regime", "mode": item.kind, "measurementMode": MEASUREMENT_MODE, "viewsSurge": surge,
              "episodeReactions": round(item.reactions), "episodeViews": round(item.views),
              "windowReactions": round(item.window_reactions), "windowViews": round(item.window_views),
              "windowStartAge": round(item.window_start), "windowEndAge": round(item.window_end),
              "ratio": round(item.ratio, 1), "surprise": round(item.surprise, 1)}
    if confirmed:
        render["plateauEvidence"] = CONFIRMED_MODE
    alternatives = (("pinned_post", "interested_audience_found_post") if item.kind == "start"
                    else ("reaction_counter_batch_update", "views_counter_delay"))
    return make_sign(PATTERN, FAMILY, prepared, Metric.REACTIONS, strength, item.start_age, item.end_age,
                     timedelta(seconds=max(item.end_age - item.start_age, 1.0)), formula, render, alternatives)
