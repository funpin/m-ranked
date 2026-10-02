"""Неизменяемые типы анализа v2.

Модуль не знает ни о базе, ни о расписании: ряд поста приходит готовым,
вывод уходит наружу как значение. Терминология — ADR-006: признак, сигнал,
аномальная динамика; слово «накрутка» здесь не появляется.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum, IntEnum
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID

PLATFORMS = frozenset({"telegram", "vk", "max", "rutube"})


class Metric(str, Enum):
    VIEWS = "views"
    REACTIONS = "reactions"
    COMMENTS = "comments"
    SHARES = "shares"


class Family(str, Enum):
    """Семейство метода. Составной подтверждённый рывок остаётся одним признаком."""

    VELOCITY = "velocity"
    SHAPE = "shape"
    CROSS_METRIC = "cross_metric"
    SYNCHRONY = "synchrony"


class Level(IntEnum):
    NONE = 0
    WEAK_SIGNAL = 1
    PRONOUNCED_ANOMALY = 2
    ARTIFICIAL_ACTIVITY_SIGNS = 3


# Паттерн 3 — свойство паттернов 1, 2 и 4 на другом масштабе, а не отдельный
# признак: он виден в поле `scale`, собственного номера у признака нет.
SIGN_PATTERNS = frozenset({1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13})


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class PostSeries:
    """Ряд замеров накопленных счётчиков одного поста.

    Значения выровнены с `observed_at`; None — метрика в замере не получена.
    Метрика, которой площадка не отдаёт вовсе, в `values` отсутствует: это не
    ноль, и детекторы по ней не работают.
    """

    publication_id: UUID
    account_id: UUID
    platform: str
    published_at: datetime
    is_repost: bool
    observed_at: tuple[datetime, ...]
    values: Mapping[Metric, tuple[int | None, ...]]
    # Account-cycle metadata is retained for compatibility. It does not prove
    # that this post or every metric was read and must not create zero deltas.
    collected: tuple[datetime, ...] = ()
    # Omission is reserved for programmatic, already validated exact series
    # (e.g. the synthetic generator). External loaders must provide qualities,
    # including "unknown" when the source does not attest precision.
    qualities: Mapping[Metric, tuple[str, ...]] | None = None
    interval_uncertain: tuple[bool, ...] = ()
    # Individual displayed counters, when retained. Never infer rounding of a
    # sum from its last digit: its components may have different precision.
    reaction_breakdowns: tuple[Mapping[str, int] | None, ...] = ()

    def __post_init__(self) -> None:
        if self.platform not in PLATFORMS:
            raise ValueError("unsupported platform")
        object.__setattr__(self, "published_at", _utc(self.published_at, "published_at"))
        instants = tuple(_utc(item, "observed_at") for item in self.observed_at)
        if any(right <= left for left, right in zip(instants, instants[1:])):
            raise ValueError("observed_at must be strictly increasing")
        object.__setattr__(self, "observed_at", instants)
        copied: dict[Metric, tuple[int | None, ...]] = {}
        for metric, column in self.values.items():
            column = tuple(column)
            if len(column) != len(instants):
                raise ValueError(f"{Metric(metric).value} is not aligned with observed_at")
            if any(item is not None and item < 0 for item in column):
                raise ValueError("cumulative counters must be non-negative")
            copied[Metric(metric)] = column
        object.__setattr__(self, "values", MappingProxyType(copied))
        quality = ({metric: ("exact",) * len(instants) for metric in copied}
                   if self.qualities is None else
                   {Metric(metric): tuple(column) for metric, column in self.qualities.items()})
        if any(len(column) != len(instants) for column in quality.values()):
            raise ValueError("quality is not aligned with observed_at")
        if any(not isinstance(item, str) for column in quality.values() for item in column):
            raise ValueError("quality entries must be strings")
        for metric in copied:
            quality.setdefault(metric, ("unknown",) * len(instants))
        uncertain = tuple(self.interval_uncertain) or (False,) * len(instants)
        if len(uncertain) != len(instants) or any(type(item) is not bool for item in uncertain):
            raise ValueError("interval_uncertain must be aligned booleans")
        object.__setattr__(self, "qualities", MappingProxyType(quality))
        object.__setattr__(self, "interval_uncertain", uncertain)
        breakdowns = tuple(self.reaction_breakdowns)
        if breakdowns and len(breakdowns) != len(instants):
            raise ValueError("reaction breakdowns are not aligned with observed_at")
        if any(type(value) is not int or value < 0 for row in breakdowns if row is not None
               for value in row.values()):
            raise ValueError("reaction breakdown counts must be non-negative integers")
        object.__setattr__(self, "reaction_breakdowns", tuple(
            None if row is None else MappingProxyType(dict(row)) for row in breakdowns))
        object.__setattr__(self, "collected",
                           tuple(sorted(_utc(item, "collected") for item in self.collected)))


    def exact_values(self, metric: Metric) -> tuple[int | None, ...] | None:
        """Values usable by point-count detectors; rounded bounds are separate."""
        column = self.values.get(metric)
        if column is None:
            return None
        return tuple(value if quality == "exact" and not uncertain else None
                     for value, quality, uncertain in zip(
                         column, self.qualities[metric], self.interval_uncertain))


@dataclass(frozen=True, slots=True)
class Interval:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _utc(self.start, "start"))
        object.__setattr__(self, "end", _utc(self.end, "end"))
        if self.end <= self.start:
            raise ValueError("interval must have positive duration")


@dataclass(frozen=True, slots=True)
class Sign:
    """Признак: один паттерн на одной метрике и одном интервале.

    `formula` — формула с подставленными числами для карточки, `render` —
    параметры отрисовки отметки на графике, `alternatives` — коды честных
    объяснений, которые детектор не смог исключить. `norm_confidence` —
    уверенность нормы, на которую опирался детектор; None — норма не нужна.
    """

    pattern: int
    family: Family
    metric: Metric
    strength: float
    interval: Interval
    scale: timedelta
    formula: str
    render: Mapping[str, Any] = field(default_factory=dict)
    alternatives: tuple[str, ...] = ()
    norm_confidence: float | None = None

    def __post_init__(self) -> None:
        if self.pattern not in SIGN_PATTERNS:
            raise ValueError("unknown sign pattern")
        if not isfinite(self.strength) or not 0 <= self.strength <= 1:
            raise ValueError("strength must be finite and in [0,1]")
        if self.scale <= timedelta(0):
            raise ValueError("scale must be positive")
        if not self.formula.strip():
            raise ValueError("formula must not be blank")
        object.__setattr__(self, "family", Family(self.family))
        object.__setattr__(self, "metric", Metric(self.metric))
        object.__setattr__(self, "render", MappingProxyType(dict(self.render)))
        object.__setattr__(self, "alternatives", tuple(self.alternatives))


@dataclass(frozen=True, slots=True)
class DataQuality:
    """Качество ряда. Интервалы из `unanalyzable` признаков не дают."""

    coverage: float
    unanalyzable: tuple[Interval, ...] = ()
    codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isfinite(self.coverage) or not 0 <= self.coverage <= 1:
            raise ValueError("coverage must be finite and in [0,1]")
        object.__setattr__(self, "unanalyzable", tuple(self.unanalyzable))
        object.__setattr__(self, "codes", tuple(self.codes))


@dataclass(frozen=True, slots=True)
class PostVerdict:
    publication_id: UUID
    level: Level
    signs: tuple[Sign, ...]
    quality: DataQuality
    detector_versions: Mapping[str, str]
    norm_version: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "level", Level(self.level))
        object.__setattr__(self, "signs", tuple(self.signs))
        object.__setattr__(self, "detector_versions", MappingProxyType(dict(self.detector_versions)))
        if self.level is not Level.NONE and not self.signs:
            raise ValueError("a non-zero level needs at least one sign")
