"""Расписание повторного анализа по возрасту поста и площадке.

Пост анализируется повторно, когда с прошлого анализа прошёл интервал из
таблицы и пришло не меньше трёх новых замеров. Исключения: замеры
возобновились после пробела — анализ сразу; окно отслеживания кончилось —
финальный анализ и заморозка; принята новая норма — перепроверка, растянутая
по окну без всплеска.

Догонка не отдельный режим, а свойство расчёта: срок всегда считается от
момента анализа, а не от пропущенного срока, поэтому после простоя каждый
просроченный пост получает ровно один анализ «на сейчас».
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timedelta
import hashlib
from typing import Mapping
from uuid import UUID

from .series import AGE_BAND_EDGES, DAY, HOUR, MINUTE

# Таблица раздела 4 плана: интервал анализа по возрастному интервалу поста
# (0–24 ч, 1–3 сут, 3–7 сут, 7–30 сут). Анализ втрое реже сбора — так между
# анализами приходит не меньше трёх новых замеров.
DEFAULT_INTERVALS = (15 * MINUTE, 45 * MINUTE, 90 * MINUTE, 3 * HOUR)
DEFAULT_RUTUBE_INTERVALS = (3 * HOUR, 3 * HOUR, 9 * HOUR, 24 * HOUR)


@dataclass(frozen=True, slots=True)
class ScheduleConfig:
    interval_day_1_seconds: int = DEFAULT_INTERVALS[0]
    interval_days_2_3_seconds: int = DEFAULT_INTERVALS[1]
    interval_days_4_7_seconds: int = DEFAULT_INTERVALS[2]
    interval_days_8_30_seconds: int = DEFAULT_INTERVALS[3]
    rutube_interval_day_1_seconds: int = DEFAULT_RUTUBE_INTERVALS[0]
    rutube_interval_days_2_3_seconds: int = DEFAULT_RUTUBE_INTERVALS[1]
    rutube_interval_days_4_7_seconds: int = DEFAULT_RUTUBE_INTERVALS[2]
    rutube_interval_days_8_30_seconds: int = DEFAULT_RUTUBE_INTERVALS[3]
    min_new_points: int = 3
    # Окно отслеживания — тот же TRACK_POST_FOR_HOURS, что у сборщиков.
    track_post_for_hours: int = 720
    # Деградация: при отставании очереди интервалы 7–30 суток растягиваются
    # до вчетверо; свежие посты не страдают никогда.
    max_stretch: float = 4.0
    stretch_after_lag_seconds: int = 15 * MINUTE
    # Перепроверка после новой нормы расходится по шести часам.
    recheck_window_seconds: int = 6 * HOUR
    # Пост без новых замеров проверяется на возобновление с шагом сбора, а не
    # с интервалом анализа: возобновившийся ряд анализируется сразу.
    stale_probe_seconds: int = 15 * MINUTE

    def __post_init__(self) -> None:
        for item in fields(self):
            if getattr(self, item.name) <= 0:
                raise ValueError(f"{item.name} must be positive")
        if self.max_stretch < 1:
            raise ValueError("max_stretch must be at least 1")

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "ScheduleConfig":
        values: dict = {}
        for item in fields(cls):
            name = "TRACK_POST_FOR_HOURS" if item.name == "track_post_for_hours" else f"ANOMALY_{item.name.upper()}"
            if name in environ:
                values[item.name] = (float if item.type in ("float", float) else int)(environ[name])
        return cls(**values)

    def intervals(self, platform: str) -> tuple[int, int, int, int]:
        if platform == "rutube":
            return (self.rutube_interval_day_1_seconds, self.rutube_interval_days_2_3_seconds,
                    self.rutube_interval_days_4_7_seconds, self.rutube_interval_days_8_30_seconds)
        return (self.interval_day_1_seconds, self.interval_days_2_3_seconds,
                self.interval_days_4_7_seconds, self.interval_days_8_30_seconds)

    @property
    def track_seconds(self) -> float:
        return self.track_post_for_hours * HOUR


@dataclass(frozen=True, slots=True)
class Plan:
    analyze: bool
    frozen: bool
    next_due_at: datetime
    reason: str


def interval(config: ScheduleConfig, platform: str, age_seconds: float, stretch: float = 1.0) -> float:
    band = min(3, max(0, int((AGE_BAND_EDGES <= age_seconds).sum()) - 1))
    base = float(config.intervals(platform)[band])
    # Растягивается только самый старый интервал — анализ свежих постов важнее.
    return base * min(max(stretch, 1.0), config.max_stretch) if band == 3 else base


def stretch_for_lag(config: ScheduleConfig, queue_lag_seconds: float) -> float:
    """Во сколько раз растянуть интервалы 7–30 суток при таком отставании очереди."""
    if queue_lag_seconds <= config.stretch_after_lag_seconds:
        return 1.0
    return min(config.max_stretch, queue_lag_seconds / config.stretch_after_lag_seconds)


def plan(config: ScheduleConfig, *, platform: str, published_at: datetime, now: datetime,
         new_points: int, analyzed_before: bool, resumed_after_gap: bool = False,
         norm_recheck: bool = False, stale: bool = False, stretch: float = 1.0) -> Plan:
    """Решение по посту, срок которого наступил."""
    age = (now - published_at).total_seconds()
    if age >= config.track_seconds:
        # Сбор прекращён: финальный анализ на всём ряду, затем заморозка.
        return Plan(True, True, now, "final")
    step = timedelta(seconds=interval(config, platform, age, stretch))
    if not analyzed_before:
        return Plan(True, False, now + step, "first")
    if resumed_after_gap:
        return Plan(True, False, now + step, "resumed")
    if norm_recheck:
        return Plan(True, False, now + step, "norm_recheck")
    if new_points >= config.min_new_points:
        return Plan(True, False, now + step, "scheduled")
    probe = timedelta(seconds=config.stale_probe_seconds) if stale else step
    return Plan(False, False, now + min(step, probe), "waiting_points")


def recheck_offset(config: ScheduleConfig, publication_id: UUID) -> timedelta:
    """Детерминированная доля окна перепроверки: без всплеска и без случайности в тестах.

    Тот же расчёт выполняет SQL хранилища: первые 32 бита md5 от идентификатора.
    """
    fraction = int(hashlib.md5(str(publication_id).encode("ascii")).hexdigest()[:8], 16)
    return timedelta(seconds=fraction % config.recheck_window_seconds)


def retry_after(attempts: int) -> timedelta:
    """Отступ повтора после ошибки поста: 1, 2, 4… минут, не больше суток."""
    return timedelta(seconds=min(DAY, MINUTE * 2 ** min(max(attempts, 0), 11)))
