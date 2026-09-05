from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol, runtime_checkable


def as_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime, preserving the legacy naive-as-UTC rule."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return as_utc(value).isoformat()


@runtime_checkable
class UtcClock(Protocol):
    """Time source used at collection and request boundaries."""

    def now(self) -> datetime:
        """Return the current instant as an aware UTC datetime."""
        ...


@dataclass(frozen=True, slots=True)
class SystemUtcClock:
    """Production clock; equivalent to the legacy datetime.now(UTC) calls."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class CallableUtcClock:
    """UTC-normalizing bridge for legacy modules with a patchable time source."""

    source: Callable[[], datetime]

    def now(self) -> datetime:
        return as_utc(self.source())


@dataclass(frozen=True, slots=True)
class FrozenUtcClock:
    """Deterministic clock for characterization and adapter contract tests."""

    instant: datetime

    def now(self) -> datetime:
        return as_utc(self.instant)
