"""Run the transfer ingest listener."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import signal

from collector_target.normalize import sanitize_error_code
from collector_target.repository import PostgresCollectorRepository
from collector_target.transfer import PostgresDataAdapter

from .config import IngestSettings
from .handler import IngestHandler
from .metrics import IngestMetrics
from .server import IngestServer, build_ssl_context


logger = logging.getLogger("transfer_ingest")


async def _run() -> int:
    repository: PostgresCollectorRepository | None = None
    try:
        settings = IngestSettings.load()
        repository = PostgresCollectorRepository(settings.database_url)
        repository.assert_schema_contract()
        server = IngestServer(
            IngestHandler(
                PostgresDataAdapter(repository),
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
        async with listener:
            await stop.wait()
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
