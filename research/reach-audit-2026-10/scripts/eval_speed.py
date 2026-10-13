"""Время анализа поста на реальных рядах: один и тот же набор постов для кода базы и кандидата.

usage: PYTHONPATH=<worktree> python -I eval_speed.py DSN [--sample 1200] [--rounds 3]

Ряды читаются один раз и анализируются `rounds` раз; печатаются p50/p95 времени
`assess` на пост по площадкам и всего. Запускать на свободной машине, базу и
кандидата подряд.
"""
import argparse
import random
import statistics
import time
from datetime import datetime, timezone

import psycopg

from anomaly_analysis.v2.levels import assess
from anomaly_analysis.v2.series import CollectionCadence
from anomaly_analysis.v2.store import PostgresAnomalyStore, SeriesTarget

AS_OF = datetime(2026, 10, 8, tzinfo=timezone.utc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dsn")
    parser.add_argument("--sample", type=int, default=1200)
    parser.add_argument("--rounds", type=int, default=3)
    arguments = parser.parse_args()
    with psycopg.connect(arguments.dsn) as connection:
        rows = connection.execute(
            """SELECT p.id, p.published_at, a.platform::text FROM ingest.visible_publication p
                 JOIN catalog.visible_platform_account a ON a.id = p.primary_account_id
                WHERE p.published_at >= '2026-09-08' AND p.published_at < '2026-10-07' ORDER BY p.id""").fetchall()
    rng = random.Random(20261012)
    by_platform = {}
    for row in rows:
        by_platform.setdefault(row[2], []).append(row)
    picked = [row for items in by_platform.values() for row in rng.sample(items, min(len(items), arguments.sample // 4))]
    store = PostgresAnomalyStore(arguments.dsn)
    series = {}
    for start in range(0, len(picked), 50):
        chunk = picked[start:start + 50]
        series.update(store.read_series([SeriesTarget(row[0], row[1]) for row in chunk]))
    cadence = CollectionCadence()
    times = {}
    for _ in range(arguments.rounds):
        for key, subject in series.items():
            if not subject.observed_at:
                continue
            started = time.perf_counter()
            assess(subject, analyzed_at=AS_OF, cadence=cadence)
            times.setdefault((subject.platform, key), []).append(time.perf_counter() - started)
    per_post = {}
    for (platform, _), values in times.items():
        per_post.setdefault(platform, []).append(min(values) * 1000)
    everything = [value for values in per_post.values() for value in values]
    for platform, values in sorted(per_post.items()) + [("all", everything)]:
        values = sorted(values)
        p95 = values[int(0.95 * (len(values) - 1))]
        print(f"{platform:<8} n={len(values):<5} p50={statistics.median(values):6.2f} ms  p95={p95:6.2f} ms  "
              f"mean={statistics.fmean(values):6.2f} ms")


if __name__ == "__main__":
    main()
