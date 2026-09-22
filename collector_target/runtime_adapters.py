"""Compatibility imports for the platform-scoped adapter modules."""
from __future__ import annotations

from collector_runtime.config import Settings

from .model import Platform
from .platforms.max import MaxGatewayCollector
from .platforms.rutube import RutubeGatewayCollector
from .platforms.telegram import (
    TelegramMtprotoCollector,
    TelegramPublicWebCollector,
    _telegram_ids,
)
from .platforms.vk import VkGatewayCollector
from .ports import MetricHistoryReader, PlatformCollector, UtcClock


def build_runtime_adapter(
    platform: Platform,
    settings: Settings,
    clock: UtcClock,
    history: MetricHistoryReader,
) -> PlatformCollector:
    """Compatibility facade; new code uses the platform registry directly."""
    from .platforms.registry import build_adapter

    return build_adapter(platform, settings, clock, history)


__all__ = [
    "MaxGatewayCollector",
    "RutubeGatewayCollector",
    "TelegramMtprotoCollector",
    "TelegramPublicWebCollector",
    "VkGatewayCollector",
    "_telegram_ids",
    "build_runtime_adapter",
]
