"""Exhaustive Platform -> adapter factory registry."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from collector_runtime.config import Settings

from ..model import Platform
from ..ports import MetricHistoryReader, PlatformCollector, UtcClock

AdapterFactory = Callable[[Settings, UtcClock, MetricHistoryReader], PlatformCollector]


@dataclass(frozen=True, slots=True)
class AdapterRegistry:
    factories: Mapping[Platform, AdapterFactory]

    def __post_init__(self) -> None:
        missing = set(Platform) - set(self.factories)
        extra = set(self.factories) - set(Platform)
        if missing or extra:
            raise ValueError(
                f"adapter registry must be exhaustive; missing={missing}, extra={extra}"
            )

    def build(
        self,
        platform: Platform,
        settings: Settings,
        clock: UtcClock,
        history: MetricHistoryReader,
    ) -> PlatformCollector:
        adapter = self.factories[Platform(platform)](settings, clock, history)
        if adapter.platform != platform:
            raise ValueError("adapter factory returned another platform")
        return adapter


def _factories() -> dict[Platform, AdapterFactory]:
    # Local imports keep the compatibility facade free from import cycles.
    from .max import build as build_max
    from .rutube import build as build_rutube
    from .telegram import build as build_telegram
    from .vk import build as build_vk

    return {
        Platform.TELEGRAM: build_telegram,
        Platform.VK: build_vk,
        Platform.MAX: build_max,
        Platform.RUTUBE: build_rutube,
    }


DEFAULT_ADAPTER_REGISTRY = AdapterRegistry(_factories())


def build_adapter(
    platform: Platform,
    settings: Settings,
    clock: UtcClock,
    history: MetricHistoryReader,
) -> PlatformCollector:
    return DEFAULT_ADAPTER_REGISTRY.build(platform, settings, clock, history)
