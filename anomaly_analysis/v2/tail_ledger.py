"""Реестр позднего отклика поста: компактная сводка для анализа аккаунта.

Поздний отклик — реакции и просмотры, пришедшие к посту в возрасте 4–14 суток.
Сравнение аккаунта с собственной историей такой отклик не видит, если он
повторяется постоянно: повторяющееся поведение становится «нормой»
(research/smart-engagement-2026-09, MAX_TAIL §4, H14). Реестр хранит то, что
позволяет сравнить пост с самим собой — долю реакций на поздние просмотры
против доли реакций в первые сутки — и с другими аккаунтами площадки.

Сводка строится из того же ряда, что уже прочитан работником, за один проход:
новых чтений замеров нет. Только точные счётчики без неопределённого
интервала; промежуточные значения не восстанавливаются, пропуск — неизвестность,
а не ноль. Исключение — Telegram: его публичные счётчики помечены как
округлённые целиком, хотя ниже десяти тысяч почти всегда точны. Для него
округлённые значения (но не неизвестной точности) допускаются, а сводка
помечается `rounded`: признак поста по ней не ставится, профиль аккаунта
сравнивается только с другими аккаунтами Telegram с той же точностью. Уменьшение счётчика (реакцию сняли) не считается приростом:
разность концов обрезается снизу нулём.

Суточная раскладка (`covered`/`growth`) — по московским суткам. День считается
покрытым, если сутки лежат между точными замерами реакций, соседние из которых
отстоят друг от друга не больше чем на 30 часов: сборщик пишет замер при
изменении и раз в сутки контрольно, поэтому прирост относится к суткам, в
которые он впервые наблюдался. После длинного пробела сутки неизвестны.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .domain import Metric, PostSeries

VERSION = 4
# Сводки третьей версии читаются: в них нет только почасовой раскладки.
READABLE_VERSIONS = (3, 4)
MOSCOW = ZoneInfo("Europe/Moscow")
HOUR = 3600
DAY = 24 * HOUR

# Ранняя точка — ближайший к суткам совместно точный замер.
EARLY_TARGET = DAY
EARLY_WINDOW = (18 * HOUR, 30 * HOUR)
# Начало позднего окна — последний точный замер не позже четырёх суток (но не
# раньше трёх); если его нет, первый в первые полсуток после четырёх.
LATE_FROM = 4 * DAY
LATE_START_WINDOW = (3 * DAY, 4 * DAY + 12 * HOUR)
LATE_UNTIL = 14 * DAY
# Окно короче суток не несёт позднего отклика — только шум счётчика.
MIN_LATE_SPAN = DAY
# Площадки, чьи округлённые счётчики допускаются в сводку с пометкой.
ROUNDED_PLATFORMS = frozenset({"telegram"})
# Соседние замеры дальше друг от друга — рост мог прийти в любые из суток пробела.
DAY_BRACKET = 30 * HOUR
# Отметки для аккаунтных находок (v2/account_findings.py): первый замер и
# ближайшие к 2, 6, 24 и 72 часам точные совместные замеры в допуске. Отметка
# 6 ч — для стартовых пакетов длиной в несколько часов (ГУАП в MAX: 50–60
# реакций за 3,5–5 ч и почти ничего потом).
FIRST_UNTIL = 30 * 60
MARKS = {"h2": (2 * HOUR, 1.5 * HOUR, 2.5 * HOUR), "h6": (6 * HOUR, 5 * HOUR, 7 * HOUR),
         "h24": (DAY, 20 * HOUR, 28 * HOUR),
         "h72": (3 * DAY, 64 * HOUR, 80 * HOUR)}
# Почасовая раскладка позднего прироста (v4) для аккаунтной находки о ночных
# реакциях: пары соседних точных замеров в возрасте от суток до 14 суток не
# дальше часа друг от друга; прирост — в час (UTC) более позднего замера.
# Просмотры и реакции берутся из одних и тех же пар, поэтому редкий ночной
# опрос сокращает их одинаково.
HOURLY_FROM = DAY
HOURLY_UNTIL = LATE_UNTIL
HOURLY_MAX_GAP = HOUR


@dataclass(frozen=True, slots=True)
class Point:
    age: float
    views: int
    reactions: int

    def payload(self) -> list[int]:
        return [round(self.age), self.views, self.reactions]


@dataclass(frozen=True, slots=True)
class TailLedger:
    early: Point | None
    start: Point | None
    end: Point | None
    covered: tuple[str, ...] = ()
    growth: Mapping[str, int] = field(default_factory=dict)
    # Хотя бы одна точка окна взята из округлённого счётчика.
    rounded: bool = False
    # Только точные замеры: первый (не позже получаса) и ближайшие к 2/24/72 ч.
    marks: Mapping[str, Point] = field(default_factory=dict)
    # Поздний прирост (просмотры[24], реакции[24]) по часу UTC; None — нет пар
    # или сводка третьей версии.
    hours: tuple[tuple[int, ...], tuple[int, ...]] | None = None

    @property
    def late(self) -> tuple[int, int] | None:
        """Чистый поздний прирост (просмотры, реакции); None — окна нет."""
        if self.start is None or self.end is None:
            return None
        return (max(0, self.end.views - self.start.views),
                max(0, self.end.reactions - self.start.reactions))

    def payload(self) -> dict[str, Any]:
        return {
            "v": VERSION,
            "early": self.early.payload() if self.early else None,
            "start": self.start.payload() if self.start else None,
            "end": self.end.payload() if self.end else None,
            "covered": list(self.covered),
            "growth": dict(self.growth),
            "rounded": self.rounded,
            "marks": {key: point.payload() for key, point in self.marks.items()},
            **({"hours": [list(self.hours[0]), list(self.hours[1])]} if self.hours else {}),
        }


def ledger_from_payload(payload: Mapping[str, Any] | None) -> TailLedger | None:
    if not payload or payload.get("v") not in READABLE_VERSIONS:
        return None

    def point(value) -> Point | None:
        return None if value is None else Point(float(value[0]), int(value[1]), int(value[2]))

    return TailLedger(point(payload.get("early")), point(payload.get("start")), point(payload.get("end")),
                      tuple(payload.get("covered") or ()),
                      {str(day): int(value) for day, value in (payload.get("growth") or {}).items()},
                      bool(payload.get("rounded", False)),
                      {str(key): point(value) for key, value in (payload.get("marks") or {}).items()},
                      _hours_from(payload.get("hours")))


def _hours_from(value) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
    if not value or len(value) != 2 or any(len(item) != 24 for item in value):
        return None
    return tuple(int(item) for item in value[0]), tuple(int(item) for item in value[1])


def build_ledger(series: PostSeries, analyzed_at: datetime | None = None) -> TailLedger:
    """Сводка позднего отклика по ряду поста на момент анализа.

    Репост получает только отметки: его просмотры собственные, но поздний
    отклик чужого содержания с профилем аккаунта не сравнивается (ADR-015).
    """
    limit = analyzed_at.timestamp() if analyzed_at is not None else float("inf")
    published = series.published_at.timestamp()
    allowed = {"exact", "rounded"} if series.platform in ROUNDED_PLATFORMS else {"exact"}
    views = _usable(series, Metric.VIEWS, allowed)
    reactions = _usable(series, Metric.REACTIONS, allowed)
    if views is None or reactions is None:
        return TailLedger(None, None, None)
    joint: list[Point] = []
    inexact: set[float] = set()
    exact_r: list[tuple[float, int]] = []
    for at, (view, view_exact), (reaction, reaction_exact) in zip(series.observed_at, views, reactions):
        instant = at.timestamp()
        if instant > limit:
            break
        age = instant - published
        if reaction is not None:
            exact_r.append((instant, reaction))
            if view is not None:
                joint.append(Point(age, view, reaction))
                if not (view_exact and reaction_exact):
                    inexact.add(age)
    marks = _marks([point for point in joint if point.age not in inexact])
    if series.is_repost:
        return TailLedger(None, None, None, marks=marks)
    early = _early(joint)
    start, end = _late_window(joint)
    covered, growth = _days(exact_r, published)
    rounded = any(point is not None and point.age in inexact for point in (early, start, end))
    return TailLedger(early, start, end, covered, growth, rounded, marks,
                      _hours(joint, inexact, published))


def _hours(points: list[Point], inexact: set[float],
           published: float) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
    """Поздний прирост по часу UTC более позднего из соседних точных замеров."""
    views, reactions = [0] * 24, [0] * 24
    counted = False
    for left, right in zip(points, points[1:]):
        if (left.age < HOURLY_FROM or right.age > HOURLY_UNTIL or right.age - left.age > HOURLY_MAX_GAP
                or left.age in inexact or right.age in inexact):
            continue
        hour = int((published + right.age) // HOUR) % 24
        views[hour] += max(0, right.views - left.views)
        reactions[hour] += max(0, right.reactions - left.reactions)
        counted = True
    return (tuple(views), tuple(reactions)) if counted else None


def _marks(points: list[Point]) -> dict[str, Point]:
    marks: dict[str, Point] = {}
    if points and points[0].age <= FIRST_UNTIL:
        marks["first"] = points[0]
    for key, (target, low, high) in MARKS.items():
        inside = [item for item in points if low <= item.age <= high]
        if inside:
            marks[key] = min(inside, key=lambda item: (abs(item.age - target), item.age))
    return marks


def _usable(series: PostSeries, metric: Metric, allowed: set[str]) -> list[tuple[int | None, bool]] | None:
    """Значение и признак точности; None на месте замера — значение непригодно."""
    column = series.values.get(metric)
    if column is None:
        return None
    return [(value if quality in allowed and not uncertain else None, quality == "exact")
            for value, quality, uncertain in zip(column, series.qualities[metric], series.interval_uncertain)]


def _early(points: list[Point]) -> Point | None:
    inside = [item for item in points if EARLY_WINDOW[0] <= item.age <= EARLY_WINDOW[1]]
    return min(inside, key=lambda item: (abs(item.age - EARLY_TARGET), item.age)) if inside else None


def _late_window(points: list[Point]) -> tuple[Point | None, Point | None]:
    before = [item for item in points if LATE_START_WINDOW[0] <= item.age <= LATE_FROM]
    start = before[-1] if before else next(
        (item for item in points if LATE_FROM < item.age <= LATE_START_WINDOW[1]), None)
    if start is None:
        return None, None
    end = next((item for item in reversed(points) if item.age <= LATE_UNTIL), None)
    if end is None or end.age - start.age < MIN_LATE_SPAN:
        return None, None
    return start, end


def _days(points: list[tuple[float, int]], published: float) -> tuple[tuple[str, ...], dict[str, int]]:
    """Московские сутки позднего окна с известным чистым приростом реакций."""
    if len(points) < 2:
        return (), {}
    instants = [item[0] for item in points]
    first_day = _moscow_midnight(published + LATE_FROM)
    if first_day.timestamp() < published + LATE_FROM:
        first_day += timedelta(days=1)
    covered: list[str] = []
    growth: dict[str, int] = {}
    day = first_day
    while day.timestamp() - published < LATE_UNTIL:
        start, end = day.timestamp(), (day + timedelta(days=1)).timestamp()
        if end > instants[-1]:
            break
        before = bisect_right(instants, start) - 1
        through = bisect_right(instants, end) - 1
        after = bisect_left(instants, end)
        if before >= 0 and all(right - left <= DAY_BRACKET
                               for left, right in zip(instants[before:after], instants[before + 1:after + 1])):
            key = day.date().isoformat()
            covered.append(key)
            delta = points[through][1] - points[before][1]
            if delta > 0:
                growth[key] = delta
        day += timedelta(days=1)
    return tuple(covered), growth


def _moscow_midnight(instant: float) -> datetime:
    local = datetime.fromtimestamp(instant, timezone.utc).astimezone(MOSCOW)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)
