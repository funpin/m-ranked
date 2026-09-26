from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import signal
import time

from .metrics import write_textfile
from .v2.schedule import ScheduleConfig
from .v2.series import CollectionCadence
from .v2.store import PostgresAnomalyStore
from .v2.worker import Worker, WorkerConfig

# Сбой базы переживается внутри процесса, как у сборщиков: пауза растёт от
# двух секунд до тридцати, а не перезапуск юнита с холодными кэшами.
TRANSIENT_BACKOFF_MIN_SECONDS = 2.0
TRANSIENT_BACKOFF_MAX_SECONDS = 30.0

log = logging.getLogger("anomaly_analysis")


def _positive(name: str, default: int, maximum: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if value < 1 or value > maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


def _transient(error: Exception) -> bool:
    try:
        import psycopg
    except ImportError:  # pragma: no cover - packaging guard
        return False
    return isinstance(error, (psycopg.OperationalError, psycopg.InterfaceError))


def main() -> None:
    parser = argparse.ArgumentParser(description="M-Ranked publication anomaly analysis worker")
    parser.add_argument("--once", action="store_true")
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    dsn = os.environ.get("ANOMALY_DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("ANOMALY_DATABASE_URL is required")
    metrics_value = os.environ.get("ANOMALY_METRICS_FILE", "").strip()
    metrics_path = Path(metrics_value) if metrics_value else None
    # Окно отслеживания и шаг сбора — те же переменные, что у сборщиков.
    worker = Worker(
        PostgresAnomalyStore(dsn), ScheduleConfig.from_environment(os.environ),
        CollectionCadence.from_environment(os.environ),
        WorkerConfig(batch_size=_positive("ANOMALY_BATCH_SIZE", 50, 200)),
        publish=lambda metrics: write_textfile(metrics_path, metrics.samples()),
    )
    poll_seconds = _positive("ANOMALY_POLL_SECONDS", 5, 300)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    backoff = TRANSIENT_BACKOFF_MIN_SECONDS
    while not stopping:
        try:
            processed = worker.run_once()
            backoff = TRANSIENT_BACKOFF_MIN_SECONDS
        except Exception as error:
            if not _transient(error) or arguments.once:
                raise
            log.warning("database unavailable, retrying in %.0fs: %s", backoff, type(error).__name__)
            time.sleep(backoff)
            backoff = min(backoff * 2, TRANSIENT_BACKOFF_MAX_SECONDS)
            continue
        if arguments.once:
            return
        # Пустая пачка — очередь догнана; полная — сразу следующая.
        if processed < worker.config.batch_size:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
