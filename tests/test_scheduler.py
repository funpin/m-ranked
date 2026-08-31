import asyncio
from types import SimpleNamespace

from app.scheduler import (
    polling_delay_seconds,
    start_polling_tasks,
    stop_polling_tasks,
)


def test_polling_delay_uses_start_to_start_cadence():
    assert polling_delay_seconds(300, 52) == 248
    assert polling_delay_seconds(300, 300) == 0
    assert polling_delay_seconds(300, 420) == 0


def test_platform_collectors_start_independently():
    async def scenario() -> None:
        started: set[str] = set()
        both_started = asyncio.Event()
        release = asyncio.Event()

        class BlockingCollector:
            def __init__(self, name: str):
                self.name = name

            async def poll_cycle(self) -> None:
                started.add(self.name)
                if len(started) == 2:
                    both_started.set()
                await release.wait()

        settings = SimpleNamespace(poll_interval_minutes=5)
        tasks = start_polling_tasks(
            (BlockingCollector("telegram"), BlockingCollector("vk")), settings,
        )
        try:
            await asyncio.wait_for(both_started.wait(), timeout=1)
            assert started == {"telegram", "vk"}
        finally:
            release.set()
            await stop_polling_tasks(tasks)

    asyncio.run(scenario())
