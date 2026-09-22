"""Run the transfer ingest listener."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import signal
import time
from typing import Any

from collector_target.normalize import sanitize_error_code
from collector_target.evidence import ImmutableEvidenceStore
from collector_target.repository import PostgresCollectorRepository
from collector_target.transfer import PostgresDataAdapter

from .config import IngestSettings
from .handler import IngestHandler
from .metrics import IngestMetrics
from .server import IngestServer, build_ssl_context


logger = logging.getLogger("transfer_ingest")


def _purge_evidence(repository: Any, settings: IngestSettings) -> int:
    """Убрать просроченные и осиротевшие объекты сырых доказательств."""
    store = ImmutableEvidenceStore(
        Path(os.environ.get(
            "COLLECTOR_RAW_EVIDENCE_DIR", "data/target-raw-evidence",
        )),
    )
    with repository._connection() as connection:
        return store.purge_expired(
            connection,
            now=datetime.now(timezone.utc),
            max_objects=settings.evidence_purge_limit,
        )


async def _release_payloads(
    adapter: PostgresDataAdapter, settings: IngestSettings, stop: asyncio.Event,
) -> None:
    """Периодически освобождать тела применённых конвертов.

    Приёмник хранил их бессрочно, и таблица росла со скоростью поступления
    данных. Строка остаётся — по ней узнаётся повторная доставка, — уходит
    только полезная нагрузка, которая после применения уже не нужна.

    Работа идёт в отдельном потоке: запросы к базе синхронные, и в цикле
    событий они задержали бы приём конвертов.
    """
    if settings.payload_retention_hours <= 0:
        logger.info("inbox payload release disabled")
        return
    last_evidence_purge = 0.0
    while not stop.is_set():
        try:
            await asyncio.sleep(settings.payload_release_interval_seconds)
        except asyncio.CancelledError:
            return
        if stop.is_set():
            return
        horizon = datetime.now(timezone.utc) - timedelta(
            hours=settings.payload_retention_hours,
        )
        try:
            released = await asyncio.to_thread(
                adapter.release_applied_payloads,
                before=horizon, limit=settings.payload_release_limit,
            )
        except Exception as error:  # noqa: BLE001 — уборка не роняет приём
            logger.warning(
                "inbox payload release failed class=%s", type(error).__name__,
            )
            continue
        if released:
            logger.info("inbox payloads released count=%s", released)

        # Файловый склад сырых доказательств своей уборки не имел: функция
        # удаления написана, но её никто не вызывал, и каталог рос до трёхсот
        # тысяч файлов. Убираем объекты с истёкшим сроком и сирот, у которых
        # строки в базе уже нет. Шаг здесь свой и редкий: проход стоит запроса
        # на каждый объект, а удалять обычно нечего.
        now = time.monotonic()
        if now - last_evidence_purge < settings.evidence_purge_interval_seconds:
            continue
        last_evidence_purge = now
        try:
            removed = await asyncio.to_thread(
                _purge_evidence, adapter.repository, settings,
            )
        except Exception as error:  # noqa: BLE001 — уборка не роняет приём
            logger.warning(
                "evidence purge failed class=%s", type(error).__name__,
            )
            continue
        if removed:
            logger.info("evidence objects purged count=%s", removed)


async def _run() -> int:
    repository: PostgresCollectorRepository | None = None
    try:
        settings = IngestSettings.load()
        repository = PostgresCollectorRepository(settings.database_url)
        repository.assert_schema_contract()
        adapter = PostgresDataAdapter(repository)
        server = IngestServer(
            IngestHandler(
                adapter,
                metrics=IngestMetrics(
                    Path(os.environ["TRANSFER_INGEST_METRICS_FILE"])
                    if os.getenv("TRANSFER_INGEST_METRICS_FILE") else None
                ),
            ),
            path=settings.path,
            allowed_producers=settings.allowed_producers,
        )
        context = build_ssl_context(
            settings.certificate, settings.private_key, settings.ca_bundle,
        )
        listener = await server.start(settings.host, settings.port, context)
        logger.info(
            "transfer ingest started host=%s port=%s path=%s producers=%s",
            settings.host, settings.port, settings.path,
            len(settings.allowed_producers),
        )
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signum, stop.set)
            except (NotImplementedError, RuntimeError):  # pragma: no cover
                pass
        release = asyncio.create_task(_release_payloads(adapter, settings, stop))
        async with listener:
            await stop.wait()
        release.cancel()
        listener.close()
        await listener.wait_closed()
        return 0
    except Exception as error:
        logger.error("transfer ingest failed code=%s", sanitize_error_code(error))
        return 1
    finally:
        if repository is not None:
            repository.close()


def main() -> int:
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
