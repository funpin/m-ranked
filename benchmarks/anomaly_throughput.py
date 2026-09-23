"""Пропускная способность анализа v2 на синтетике Сервера 2.

Популяция — ~29 000 активных постов с равномерным возрастом в окне тридцати
суток и долями площадок по составу каталога; ряды — шаг сбора по возрасту,
не больше 1 200 точек. По таблице расписания считается, сколько анализов в
час нужно такой популяции, а на стратифицированной выборке меряется, сколько
стоит один анализ: подготовка ряда, детекторы, сборка уровня — при зрелой
норме площадки. Произведение даёт среднюю загрузку ядра.

Чтение рядов из базы здесь не меряется — для этого нужен стенд; бюджет
50 мс на пост делится между чтением и расчётом, и отчёт показывает, сколько
из него съедает расчёт.

    .venv/bin/python benchmarks/anomaly_throughput.py --sample 3000
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import platform as host
import resource
import sys
import time
from pathlib import Path
from uuid import UUID

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anomaly_analysis.v2.detectors import DetectorContext  # noqa: E402
from anomaly_analysis.v2.domain import Metric, PostSeries  # noqa: E402
from anomaly_analysis.v2.levels import run_detectors, verdict  # noqa: E402
from anomaly_analysis.v2.norms import build_norms  # noqa: E402
from anomaly_analysis.v2.schedule import ScheduleConfig, interval  # noqa: E402
from anomaly_analysis.v2.series import DAY, HOUR, CollectionCadence, age_band, prepare  # noqa: E402

PLATFORM_SHARES = {"telegram": 0.40, "vk": 0.35, "max": 0.15, "rutube": 0.10}
METRICS = {"telegram": (Metric.VIEWS, Metric.REACTIONS, Metric.COMMENTS),
           "vk": (Metric.VIEWS, Metric.REACTIONS, Metric.COMMENTS, Metric.SHARES),
           "max": (Metric.VIEWS, Metric.REACTIONS, Metric.COMMENTS),
           "rutube": (Metric.VIEWS, Metric.REACTIONS, Metric.COMMENTS)}
SHAPE = {"telegram": (1.5, 0.8), "vk": (3.0, 0.6), "max": (1.2, 0.85), "rutube": (12.0, 0.5)}
MAX_POINTS = 1200
BUDGET_MS = 50.0
BUDGET_CORES = 0.2
BUDGET_MEMORY_MB = 384
NOW = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
CADENCE = CollectionCadence()
SCHEDULE = ScheduleConfig()


def synthetic(rng: np.random.Generator, index: int, platform: str, age: float, *, pumped: bool = False,
              account: int = 0) -> PostSeries:
    published = NOW - timedelta(seconds=age)
    ages, point = [], float(rng.integers(90, 300))
    while point <= age and len(ages) < MAX_POINTS:
        ages.append(point)
        point += float(CADENCE.expected_step_seconds(platform, np.array([point]))[0]) + float(rng.integers(-15, 15))
    hours = np.asarray(ages) / HOUR
    c, theta = SHAPE[platform]
    total = 6000 * float(rng.lognormal(0, 0.5))
    views = total * (1 - (1 + hours / c) ** -theta)
    if pumped and hours[-1] > 36:
        views = views + np.clip((hours - 30) / 24, 0, 1) * total
    views = np.maximum.accumulate(np.round(views + rng.normal(0, 1, views.size) * np.sqrt(np.maximum(views, 1))))
    values = {Metric.VIEWS: views}
    for metric, share in ((Metric.REACTIONS, 0.02), (Metric.COMMENTS, 0.002), (Metric.SHARES, 0.004)):
        if metric in METRICS[platform]:
            values[metric] = np.maximum.accumulate(np.round(views * share * float(rng.lognormal(0, 0.1))))
    return PostSeries(UUID(int=index + 1), UUID(int=10_000_000 + account), platform, published, False,
                      tuple(published + timedelta(seconds=item) for item in ages),
                      {metric: tuple(int(value) for value in column) for metric, column in values.items()})


def population(rng: np.random.Generator, size: int):
    platforms = rng.choice(list(PLATFORM_SHARES), size=size, p=list(PLATFORM_SHARES.values()))
    ages = rng.uniform(10 * 60, SCHEDULE.track_seconds, size=size)
    return platforms, ages


def hourly_load(platforms: np.ndarray, ages: np.ndarray) -> float:
    return float(sum(HOUR / interval(SCHEDULE, str(p), float(a)) for p, a in zip(platforms, ages)))


def mature_norms(rng: np.random.Generator):
    norms = {}
    for platform in PLATFORM_SHARES:
        posts = {}
        for account in range(20):
            items = [synthetic(rng, 5_000_000 + account * 10 + index, platform, 10 * DAY, account=account)
                     for index in range(4)]
            posts[UUID(int=10_000_000 + account)] = [prepare(item, item.observed_at[-1], CADENCE) for item in items]
        norms[platform] = build_norms(platform, posts, final_age=7 * DAY)
    return norms


def peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 1024 / 1024 if sys.platform == "darwin" else peak / 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--posts", type=int, default=29_000)
    parser.add_argument("--sample", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=20260923)
    parser.add_argument("--json", type=Path)
    arguments = parser.parse_args()
    rng = np.random.default_rng(arguments.seed)
    platforms, ages = population(rng, arguments.posts)
    required = hourly_load(platforms, ages)
    norms = mature_norms(rng)
    chosen = rng.choice(arguments.posts, size=min(arguments.sample, arguments.posts), replace=False)
    timings = {"prepare": [], "detectors": [], "level": [], "total": []}
    by_band: dict[int, list[float]] = {}
    points = []
    batch = []
    for order, index in enumerate(chosen):
        platform, age = str(platforms[index]), float(ages[index])
        series = synthetic(rng, int(index), platform, age, pumped=order % 20 == 0, account=int(index) % 400)
        points.append(len(series.observed_at))
        # Работник держит в памяти пачку из 50 рядов — так же и здесь.
        batch.append(series)
        if len(batch) > 50:
            batch.pop(0)
        started = time.perf_counter()
        prepared = prepare(series, NOW, CADENCE)
        prepared_at = time.perf_counter()
        norm_set = norms[platform]
        context = DetectorContext(platform, norm_set.for_account(series.account_id))
        signs, versions = run_detectors(prepared, context)
        detected_at = time.perf_counter()
        verdict(prepared, context, signs, versions)
        finished = time.perf_counter()
        timings["prepare"].append(prepared_at - started)
        timings["detectors"].append(detected_at - prepared_at)
        timings["level"].append(finished - detected_at)
        timings["total"].append(finished - started)
        by_band.setdefault(int(age_band(np.array([age]))[0]), []).append(finished - started)
    mean_by_band = {band: float(np.mean(values)) for band, values in by_band.items()}
    seconds_per_hour = sum(HOUR / interval(SCHEDULE, str(p), float(a)) * mean_by_band[min(3, int(age_band(np.array([a]))[0]))]
                           for p, a in zip(platforms, ages))
    cores = seconds_per_hour / HOUR
    total = np.array(timings["total"]) * 1000
    report = {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "host": f"{host.machine()} · Python {host.python_version()} · numpy {np.__version__}",
        "posts": arguments.posts, "sample": int(chosen.size),
        "points_p50": float(np.median(points)), "points_max": int(max(points)),
        "required_analyses_per_hour": round(required),
        "ms": {stage: {"p50": round(float(np.percentile(np.array(values) * 1000, 50)), 2),
                       "p95": round(float(np.percentile(np.array(values) * 1000, 95)), 2)}
               for stage, values in timings.items()},
        "mean_ms_by_age_band": {str(band): round(value * 1000, 2) for band, value in sorted(mean_by_band.items())},
        "analyses_per_hour_one_core": round(HOUR / float(np.mean(timings["total"]))),
        "average_cores": round(cores, 3),
        "peak_rss_mb": round(peak_rss_mb(), 1),
    }
    report["within_budget"] = bool(total.max() <= BUDGET_MS * 2 and np.percentile(total, 95) <= BUDGET_MS
                                   and cores <= BUDGET_CORES and report["peak_rss_mb"] <= BUDGET_MEMORY_MB)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if arguments.json:
        arguments.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["within_budget"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
