from __future__ import annotations

from dataclasses import dataclass
from inspect import isawaitable
from typing import Awaitable, Callable

from .model import AccountRef, CollectionContext, Platform, RawCollectionBatch
from .platforms.max import max_batch
from .platforms.rutube import rutube_batch
from .platforms.telegram import telegram_batch, telegram_public_batch
from .platforms.vk import vk_batch


BatchFactory = Callable[
    [AccountRef, CollectionContext],
    RawCollectionBatch | Awaitable[RawCollectionBatch],
]


@dataclass(slots=True)
class DelegatingPlatformCollector:
    """Compatibility adapter seam for externally supplied batch factories."""

    platform: Platform
    factory: BatchFactory

    async def collect(
        self,
        account: AccountRef,
        context: CollectionContext,
    ) -> RawCollectionBatch:
        if account.platform != self.platform or context.platform != self.platform:
            raise ValueError("gateway adapter platform mismatch")
        result = self.factory(account, context)
        return await result if isawaitable(result) else result

    async def close(self) -> None:
        return None


__all__ = [
    "DelegatingPlatformCollector",
    "max_batch",
    "rutube_batch",
    "telegram_batch",
    "telegram_public_batch",
    "vk_batch",
]
