from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import time

from .config import default_manifest
from .coordinator import AnalysisCoordinator, WorkerConfig
from .metrics import TextfileMetrics
from .postgres import PostgresAnalysisRepository


def _positive(name: str, default: int, maximum: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if value < 1 or value > maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="M-Ranked publication anomaly analysis worker")
    parser.add_argument("--once", action="store_true")
    arguments = parser.parse_args()
    dsn = os.environ.get("ANOMALY_DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("ANOMALY_DATABASE_URL is required")
    config = WorkerConfig(
        batch_size=_positive("ANOMALY_BATCH_SIZE", 20, 100),
        lease_seconds=_positive("ANOMALY_LEASE_SECONDS", 120, 900),
        max_points_per_publication=_positive("ANOMALY_MAX_POINTS", 4096, 10000),
        retry_base_seconds=_positive("ANOMALY_RETRY_BASE_SECONDS", 30, 3600),
        retry_max_seconds=_positive("ANOMALY_RETRY_MAX_SECONDS", 3600, 86400),
        backfill_batch_size=_positive("ANOMALY_BACKFILL_BATCH_SIZE", 50, 1000),
        backfill_interval_seconds=_positive("ANOMALY_BACKFILL_INTERVAL_SECONDS", 300, 86400),
    )
    metrics_value = os.environ.get("ANOMALY_METRICS_FILE", "").strip()
    coordinator = AnalysisCoordinator(PostgresAnalysisRepository(dsn), default_manifest(), config,
                                      TextfileMetrics(Path(metrics_value) if metrics_value else None))
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    poll_seconds = _positive("ANOMALY_POLL_SECONDS", 5, 300)
    while not stopping:
        processed = coordinator.run_once()
        if arguments.once:
            return
        if not processed:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
