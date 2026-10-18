"""Контракт хранилища бота на MemoryStore (без базы)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from telegram_bot.store import MemoryStore
from tests.telegram_bot_store_contract import CASES


async def _run(case) -> None:
    store = MemoryStore()

    async def seed_host_sample(observed_at, sample) -> None:
        store.host_samples.append({"observed_at": observed_at, "sample": sample})

    await case(SimpleNamespace(store=store, seed_host_sample=seed_host_sample))


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.__name__)
def test_memory_store_contract(case) -> None:
    asyncio.run(_run(case))
