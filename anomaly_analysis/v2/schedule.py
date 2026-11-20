"""Расписание повторного анализа по возрасту поста и площадке.

Пост анализируется повторно, когда с прошлого анализа прошёл интервал из
таблицы и пришло не меньше трёх новых замеров. Исключения: замеры
возобновились после пробела — анализ сразу; окно отслеживания кончилось —
финальный анализ и заморозка; вывод поста посчитан по норме старше недели —
перепроверка, растянутая по окну без всплеска.

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
    # Окно постановки в очередь шире окна отслеживания: сайт показывает посты
    # за 70 суток, и каждый из них должен иметь вывод. Пост старше окна
    # отслеживания получает один финальный анализ и замораживается.
    seed_window_hours: int = 75 * 24
    # Деградация: при отставании очереди интервалы 7–30 суток растягиваются
    # до вчетверо; свежие посты не страдают никогда. Растянутый срок поста —
    # его доля между обычным и растянутым интервалом (stretch_share): с
    # одинаковым множителем вся когорта приходила одной волной через 12 ч.
    max_stretch: float = 4.0
    stretch_after_lag_seconds: int = 15 * MINUTE
    # Новая норма принимается каждую ночь и сдвигается на сотые доли MAD:
    # суточная смена меняет 0.2 % выводов, недельная — 1 %, и только между
    # уровнями 0 и 1 (замер на копии прода 20.11.2026). Пост с новыми замерами
    # и так получает свежую норму в очередном анализе; принудительно
    # перепроверяется только вывод по норме старше этого срока.
    norm_recheck_after_seconds: int = 7 * DAY
    # Перепроверка расходится по суткам: прежние шесть часов вместе с ежесуточной
    # перепроверкой всех постов давали утренний вал очереди (до 3.4 ч, 20.11).
    recheck_window_seconds: int = DAY
    # Пост без новых замеров проверяется на возобновление с шагом сбора, а не
    # с интервалом анализа: возобновившийся ряд анализируется сразу.
    stale_probe_seconds: int = 15 * MINUTE
    # Долго молчащий ряд пробуется реже: шаг пробы — эта доля от длительности
    # молчания, но не меньше шага выше и не больше интервала анализа возраста.
    # Каждая проба — перезапись широкой строки состояния; 16.10 на проде
    # пробы замолчавших постов давали почти все обновления таблицы.
    stale_probe_backoff: float = 0.1

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

    @property
    def seed_seconds(self) -> float:
        return max(self.seed_window_hours, self.track_post_for_hours) * HOUR


@dataclass(frozen=True, slots=True)
class Plan:
    analyze: bool
    frozen: bool
    next_due_at: datetime
    reason: str


def interval(config: ScheduleConfig, platform: str, age_seconds: float, stretch: float = 1.0,
             spread: float = 1.0) -> float:
    """Интервал анализа; `spread` — доля поста в растяжке (1 — растянуть полностью)."""
    band = min(3, max(0, int((AGE_BAND_EDGES <= age_seconds).sum()) - 1))
    base = float(config.intervals(platform)[band])
    # Растягивается только самый старый интервал — анализ свежих постов важнее.
    if band != 3:
        return base
    factor = min(max(stretch, 1.0), config.max_stretch)
    return base * (1.0 + (factor - 1.0) * min(max(spread, 0.0), 1.0))


def stretch_share(publication_id: UUID) -> float:
    """Доля поста в растяжке интервала, [0, 1): детерминированно по идентификатору.

    Берутся вторые 32 бита md5 — не те, что у recheck_offset, чтобы доля
    растяжки не повторяла место поста в окне перепроверки.
    """
    return int(hashlib.md5(str(publication_id).encode("ascii")).hexdigest()[8:16], 16) / 2.0 ** 32


def stretch_for_lag(config: ScheduleConfig, queue_lag_seconds: float) -> float:
    """Во сколько раз растянуть интервалы 7–30 суток при таком отставании очереди."""
    if queue_lag_seconds <= config.stretch_after_lag_seconds:
        return 1.0
    return min(config.max_stretch, queue_lag_seconds / config.stretch_after_lag_seconds)


def plan(config: ScheduleConfig, *, platform: str, published_at: datetime, now: datetime,
         new_points: int, analyzed_before: bool, resumed_after_gap: bool = False,
         norm_recheck: bool = False, stale: bool = False, stretch: float = 1.0,
         reference_checkpoint: bool = False, tail_ledger_stale: bool = False,
         silent_seconds: float = 0.0, spread: float = 1.0) -> Plan:
    """Решение по посту, срок которого наступил; `spread` — stretch_share поста."""
    age = (now - published_at).total_seconds()
    if age >= config.track_seconds:
        # Сбор прекращён: финальный анализ на всём ряду, затем заморозка.
        return Plan(True, True, now, "final")
    step = timedelta(seconds=interval(config, platform, age, stretch, spread))
    if not analyzed_before:
        return Plan(True, False, now + step, "first")
    if resumed_after_gap:
        return Plan(True, False, now + step, "resumed")
    if norm_recheck:
        return Plan(True, False, now + step, "norm_recheck")
    if reference_checkpoint:
        return Plan(True, False, now + step, "reference_checkpoint")
    if tail_ledger_stale:
        # Сводки позднего отклика нет или она старого формата: один анализ её строит.
        return Plan(True, False, now + step, "tail_ledger")
    if new_points >= config.min_new_points:
        return Plan(True, False, now + step, "scheduled")
    # Возобновление после пробела анализируется сразу, как только проба его
    # увидит; отступ пробы ограничен интервалом анализа, поэтому задержка не
    # больше той, что у поста с обычным сбором.
    probe = (timedelta(seconds=max(config.stale_probe_seconds, config.stale_probe_backoff * silent_seconds))
             if stale else step)
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
