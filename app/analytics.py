from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Iterable, Mapping, Sequence


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def age_seconds(published_at: datetime, measured_at: datetime) -> int:
    return max(0, int((ensure_utc(measured_at) - ensure_utc(published_at)).total_seconds()))


def history_is_complete(first_age_seconds: int, max_minutes: int) -> bool:
    return first_age_seconds <= max_minutes * 60


def delta_by_reaction(current: Mapping[str, int], previous: Mapping[str, int]) -> dict[str, int]:
    return {
        key: int(current.get(key, 0)) - int(previous.get(key, 0))
        for key in sorted(set(current) | set(previous))
        if int(current.get(key, 0)) - int(previous.get(key, 0)) != 0
    }


def is_spike(previous_total: int, current_total: int, min_abs: int, min_ratio: float) -> bool:
    jump = current_total - previous_total
    ratio = current_total / max(previous_total, 1)
    return jump >= min_abs and ratio >= min_ratio


def hourly_bucket(age_in_seconds: int) -> int:
    return max(0, age_in_seconds // 3600)


def interval_uncertain(delta_seconds: int, expected_minutes: int, tolerance: float = 1.5) -> bool:
    return delta_seconds > expected_minutes * 60 * tolerance


def nearest_hourly_points(rows: Sequence[Mapping[str, float]], max_hour: int) -> dict[int, float]:
    points: dict[int, float] = {}
    for hour in range(max_hour + 1):
        candidates = [row for row in rows if abs(float(row["age_seconds"]) / 3600 - hour) <= 0.75]
        if candidates:
            closest = min(candidates, key=lambda row: abs(float(row["age_seconds"]) / 3600 - hour))
            points[hour] = float(closest["total_reactions"])
    return points


def hourly_asof_points(rows: Sequence[Mapping[str, float]], max_hour: int) -> dict[int, float]:
    """Return the latest value known at each whole hour without using future data."""
    ordered = sorted(rows, key=lambda row: float(row["age_seconds"]))
    points: dict[int, float] = {}
    index = 0
    latest: Mapping[str, float] | None = None
    for hour in range(max_hour + 1):
        target = hour * 3600
        while index < len(ordered) and float(ordered[index]["age_seconds"]) <= target:
            latest = ordered[index]
            index += 1
        if latest is not None:
            points[hour] = float(latest["total_reactions"])
    return points


def median_curve(post_points: Iterable[Mapping[int, float]], max_hour: int) -> list[float | None]:
    posts = list(post_points)
    return [
        median(values) if (values := [post[h] for post in posts if h in post]) else None
        for h in range(max_hour + 1)
    ]


def fixed_cohort_median_curve(
    post_points: Iterable[Mapping[int, float]],
    max_hour: int,
    start_hour: int = 0,
) -> tuple[list[float | None], list[int], int]:
    """Build a curve from one cohort that covers the complete requested horizon."""
    cohort = [
        post for post in post_points
        if start_hour in post and max_hour in post
    ]
    curve: list[float | None] = []
    counts: list[int] = []
    for hour in range(max_hour + 1):
        values = [post[hour] for post in cohort if hour in post]
        curve.append(median(values) if values else None)
        counts.append(len(values))
    return curve, counts, len(cohort)
