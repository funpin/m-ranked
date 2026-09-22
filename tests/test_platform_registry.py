from __future__ import annotations

from dataclasses import dataclass
import asyncio
from typing import Any

import pytest

from collector_target.model import Platform, RawCollectionBatch
from collector_target.platforms.registry import AdapterRegistry
from collector_target.ports import PlatformCollector
from collector_target.runtime_adapters import (
    MaxGatewayCollector,
    RutubeGatewayCollector,
    TelegramMtprotoCollector,
    TelegramPublicWebCollector,
    VkGatewayCollector,
)


@dataclass
class _Adapter:
    platform: Platform
    closed: bool = False

    async def collect(self, account: Any, context: Any) -> RawCollectionBatch:
        raise NotImplementedError

    async def close(self) -> None:
        self.closed = True


def _factory(platform: Platform):
    def build(settings: Any, clock: Any, history: Any) -> PlatformCollector:
        return _Adapter(platform)

    return build


def test_registry_is_exhaustive_and_returns_the_requested_adapter() -> None:
    registry = AdapterRegistry({platform: _factory(platform) for platform in Platform})

    for platform in Platform:
        adapter = registry.build(platform, object(), object(), object())  # type: ignore[arg-type]
        assert isinstance(adapter, PlatformCollector)
        assert adapter.platform == platform
        assert not hasattr(adapter, "persist_account_batch")


def test_registry_rejects_missing_or_mismatched_platforms() -> None:
    with pytest.raises(ValueError, match="exhaustive"):
        AdapterRegistry({Platform.TELEGRAM: _factory(Platform.TELEGRAM)})

    registry = AdapterRegistry({platform: _factory(platform) for platform in Platform})
    broken = dict(registry.factories)
    broken[Platform.VK] = _factory(Platform.MAX)
    with pytest.raises(ValueError, match="another platform"):
        AdapterRegistry(broken).build(
            Platform.VK, object(), object(), object(),  # type: ignore[arg-type]
        )


def test_platform_adapter_close_is_idempotent() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls = 0

        async def close(self) -> None:
            self.calls += 1

        async def aclose(self) -> None:
            self.calls += 1

        async def disconnect(self) -> None:
            self.calls += 1

    async def check() -> None:
        for collector_type in (
            TelegramMtprotoCollector,
            TelegramPublicWebCollector,
            VkGatewayCollector,
            MaxGatewayCollector,
            RutubeGatewayCollector,
        ):
            client = Client()
            collector = object.__new__(collector_type)
            collector._closed = False
            if collector_type is TelegramMtprotoCollector:
                collector.reader = client
            else:
                collector.client = client
            if collector_type is TelegramPublicWebCollector:
                collector._owns_client = True
                collector.comments_reader = None
            await collector.close()
            await collector.close()
            assert client.calls == 1

    asyncio.run(check())
