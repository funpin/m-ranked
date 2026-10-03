"""Политика сбора и состав сборщиков, которые меняются без перезапуска.

Панель управления на Сервере 2 хранит политику сбора и реестр серверов.
Агент узла (operations/storage/agent.py) раз в минуту получает их и атомарно
пишет файл runtime.json. Сборщик перечитывает файл в начале каждого цикла, если
он изменился: новые интервалы опроса и срок слежения действуют с этого цикла,
а новый состав участников сразу перераспределяет аккаунты (рандеву-хеш,
placement.py). Нет файла или он повреждён — работают значения окружения, как
раньше: сбор не зависит от доступности Сервера 2.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger("collector.runtime_policy")

# Ключ политики → поле настроек и множитель. Значение null — значение окружения.
SETTING_KEYS: dict[str, tuple[str, int]] = {
    "trackPostDays": ("track_post_for_hours", 24),
    "pollIntervalMinutes": ("poll_interval_minutes", 1),
    "secondDayPollIntervalMinutes": ("second_day_poll_interval_minutes", 1),
    "thirdDayPollIntervalMinutes": ("third_day_poll_interval_minutes", 1),
    "days4To6PollIntervalMinutes": ("days_4_to_6_poll_interval_minutes", 1),
    "days7To13PollIntervalMinutes": ("days_7_to_13_poll_interval_minutes", 1),
    "day14PlusPollIntervalMinutes": ("day_14_plus_poll_interval_minutes", 1),
    "refreshLimit": ("collector_refresh_limit", 1),
}
# Пределы защищают сбор от опечатки в панели: интервал в ноль минут положил бы
# площадку запросами, срок слежения в тысячу дней — базу.
LIMITS: dict[str, tuple[int, int]] = {
    "trackPostDays": (1, 120),
    "snapshotHeartbeatHours": (1, 720),
    "pollIntervalMinutes": (1, 1440),
    "secondDayPollIntervalMinutes": (1, 1440),
    "thirdDayPollIntervalMinutes": (1, 1440),
    "days4To6PollIntervalMinutes": (1, 1440),
    "days7To13PollIntervalMinutes": (1, 1440),
    "day14PlusPollIntervalMinutes": (1, 10080),
    "refreshLimit": (1, 2000),
}


def validate_collection_policy(value: Mapping[str, Any]) -> dict[str, int | None]:
    """Нормализовать политику сбора; лишние ключи и выход за пределы — ошибка."""
    unknown = set(value) - set(LIMITS) - {"heartbeatMaxAgeDays"}
    if unknown:
        raise ValueError(f"unknown collection policy keys: {sorted(unknown)}")
    result: dict[str, int | None] = {}
    for key, (low, high) in LIMITS.items():
        raw = value.get(key)
        if raw is None:
            result[key] = None
            continue
        if isinstance(raw, bool) or not isinstance(raw, int) or not low <= raw <= high:
            raise ValueError(f"{key} must be an integer in [{low}; {high}]")
        result[key] = raw
    max_age = value.get("heartbeatMaxAgeDays")
    if max_age is not None and (isinstance(max_age, bool) or not isinstance(max_age, int) or not 1 <= max_age <= 3650):
        raise ValueError("heartbeatMaxAgeDays must be an integer in [1; 3650]")
    result["heartbeatMaxAgeDays"] = max_age
    return result


class RuntimeSettings:
    """Настройки окружения с поверх наложенной политикой из панели."""

    def __init__(self, base: Any) -> None:
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_overrides", {})

    def __getattr__(self, name: str) -> Any:
        overrides = object.__getattribute__(self, "_overrides")
        if name in overrides:
            return overrides[name]
        return getattr(object.__getattribute__(self, "_base"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("runtime settings are read-only")

    def apply(self, overrides: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_overrides", dict(overrides))


@dataclass(frozen=True, slots=True)
class RuntimeState:
    membership: str | None
    overrides: dict[str, Any]
    heartbeat_hours: int | None
    version: str
    heartbeat_max_age_days: int | None = None


def parse_runtime(document: Mapping[str, Any], base: Any) -> RuntimeState:
    policy = validate_collection_policy(document.get("collection") or {})
    overrides: dict[str, Any] = {}
    for key, (field, factor) in SETTING_KEYS.items():
        value = policy.get(key)
        if value is not None:
            overrides[field] = value * factor
    # Перекрытие не должно нарушить связь лимитов: обход не меньше обновления.
    if "collector_refresh_limit" in overrides:
        scan = getattr(base, "collector_refresh_scan_limit", 400)
        overrides["collector_refresh_limit"] = min(overrides["collector_refresh_limit"], scan)
    membership = document.get("membership")
    if membership is not None and not isinstance(membership, str):
        raise ValueError("membership must be a string")
    return RuntimeState(membership or None, overrides, policy.get("snapshotHeartbeatHours"),
                        str(document.get("version", "")), policy.get("heartbeatMaxAgeDays"))


class RuntimeOverlay:
    """Файл runtime.json с проверкой изменения по mtime и размеру."""

    def __init__(self, path: str | os.PathLike[str] | None, base: Any) -> None:
        self.path = Path(path) if path else None
        self.base = base
        self._stamp: tuple[int, int] | None = None
        self.state: RuntimeState | None = None

    def refresh(self) -> bool:
        """Перечитать файл; True — политика или состав изменились."""
        if self.path is None:
            return False
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            changed = self.state is not None
            self._stamp, self.state = None, None
            return changed
        stamp = (stat.st_mtime_ns, stat.st_size)
        if stamp == self._stamp:
            return False
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            state = parse_runtime(document, self.base)
        except (OSError, ValueError) as error:
            # Повреждённый файл не останавливает сбор: остаётся прежняя политика.
            logger.warning("collector runtime policy ignored code=%s", type(error).__name__)
            self._stamp = stamp
            return False
        self._stamp = stamp
        changed = state != self.state
        self.state = state
        return changed
