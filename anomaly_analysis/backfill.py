"""Разовая перепроверка постов окна с агрегатами аккаунта на всё окно.

Работник смотрит синхронность по агрегатам последних трёх суток: так память
не растёт с глубиной, а найденный признак потом переносится из прежнего
вывода. Но после смены методики событие недельной давности (вброс на посты
Московского Политеха 02.09) работник заново не найдёт — его окно уже ушло.
Перепроверка идёт аккаунт за аккаунтом: агрегаты одного аккаунта за всё окно
читаются одним запросом, все его посты анализируются с ними, и результат
пишется тем же путём, что у работника. Память — на один аккаунт.

Запускать при остановленном работнике: иначе он может перезаписать пост
выводом без найденного здесь признака.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import logging
import os
import shutil
import time

from .v2.levels import assess
from .v2.schedule import ScheduleConfig, plan
from .v2.series import CollectionCadence
from .v2.store import SERIES_BATCH, PostgresAnomalyStore, SeriesTarget, StateWrite

log = logging.getLogger("anomaly_analysis.backfill")
PLATFORMS = ("telegram", "vk", "max", "rutube")


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-analyse every post of the window with full account activity")
    parser.add_argument("--days", type=int, default=35)
    arguments = parser.parse_args()
    if not 1 <= arguments.days <= 75:
        raise SystemExit("--days must be between 1 and 75")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    dsn = os.environ.get("ANOMALY_DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("ANOMALY_DATABASE_URL is required")
    disk_path = os.environ.get("MRANKED_STORAGE_PATH", "/var/lib/m-ranked")
    peak_bytes = int(os.environ.get("MRANKED_BACKFILL_PEAK_BYTES", "1000000000"))
    def require_space():
        if peak_bytes < 1:
            raise SystemExit("positive backfill disk budget required")
        try:
            usage = shutil.disk_usage(disk_path)
            fs = os.statvfs(disk_path)
        except OSError:
            raise SystemExit("backfill stopped: disk probe unavailable") from None
        if usage.free < usage.total // 5 + peak_bytes or (fs.f_files and fs.f_favail <= fs.f_files // 10):
            raise SystemExit("backfill stopped: insufficient disk reserve")
    require_space()
    store = PostgresAnomalyStore(dsn)
    schedule = ScheduleConfig.from_environment(os.environ)
    cadence = CollectionCadence.from_environment(os.environ)
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=arguments.days)
    version = store.latest_accepted_norm_version()
    norms = {platform: store.read_norms(version, platform) for platform in PLATFORMS} if version else {}
    accounts = store.backfill_accounts(since)
    log.info("backfill started accounts=%d days=%d norm_version=%s", len(accounts), arguments.days, version)
    analyzed = failed = 0
    for position, account in enumerate(accounts, 1):
        require_space()
        started = time.monotonic()
        rows = store.backfill_targets(account, since)
        # Агрегаты — с суток до самого старого поста: базе подъёма нужен хвост.
        activity = store.read_activity([account], since - timedelta(days=1), now,
                                       since - timedelta(days=1)).get(account)
        subscribers = store.read_subscribers([account], since - timedelta(days=1), now).get(account) or ()
        for start in range(0, len(rows), SERIES_BATCH):
            require_space()
            chunk = rows[start:start + SERIES_BATCH]
            series = store.read_series([SeriesTarget(row.publication_id, row.published_at) for row in chunk])
            writes: list[StateWrite] = []
            moment = datetime.now(timezone.utc)
            for row in chunk:
                subject = series.get(row.publication_id)
                if subject is None or not subject.observed_at:
                    continue
                try:
                    verdict = assess(subject, norms=norms.get(subject.platform), subscribers=subscribers,
                                     analyzed_at=moment, cadence=cadence, norm_version=version,
                                     activity=activity)
                except Exception:  # один пост не останавливает перепроверку
                    failed += 1
                    log.exception("backfill post failed publication=%s", row.publication_id)
                    continue
                decision = plan(schedule, platform=subject.platform, published_at=subject.published_at,
                                now=moment, new_points=len(subject.observed_at), analyzed_before=False)
                writes.append(StateWrite(
                    row.publication_id, row.published_at, moment, decision.next_due_at, verdict=verdict,
                    analyzed_points=len(subject.observed_at), last_point_observed_at=subject.observed_at[-1],
                    norm_version_id=version, frozen=decision.frozen, lag_seconds=0, reason="backfill"))
                analyzed += 1
            store.write_states(writes)
        log.info("backfill account %d/%d posts=%d seconds=%.1f", position, len(accounts), len(rows),
                 time.monotonic() - started)
    log.info("backfill finished analyzed=%d failed=%d", analyzed, failed)


if __name__ == "__main__":
    main()
