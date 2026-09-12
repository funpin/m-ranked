from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import median
from typing import Iterable

from .domain import MetricObservation, MetricSegment

PREPROCESSING_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class LinearFit:
    slope: float
    intercept: float
    r_squared: float
    normalized_rmse: float


@dataclass(frozen=True, slots=True)
class PreparedSeries:
    observations: tuple[MetricObservation, ...]
    real_observations: tuple[MetricObservation, ...]
    segments: tuple[MetricSegment, ...]
    coverage: float
    maximum_gap_seconds: float
    bound_exceeded: bool = False


def robust_median(values: Iterable[float]) -> float:
    materialized = tuple(values)
    return float(median(materialized)) if materialized else 0.0


def median_absolute_deviation(values: Iterable[float]) -> float:
    materialized = tuple(values)
    if not materialized:
        return 0.0
    center = median(materialized)
    return float(median(abs(value - center) for value in materialized))


def prepare_metric(
    observations: Iterable[MetricObservation], *, max_points: int = 4096
) -> PreparedSeries:
    ordered = tuple(sorted(observations, key=lambda item: (
        item.observed_at, item.snapshot_id, item.correction_sequence
    )))
    if len(ordered) > max_points:
        return PreparedSeries(ordered[:max_points], (), (), 0.0, 0.0, True)

    # Exact duplicates cannot manufacture evidence. Corrections with distinct IDs
    # remain visible; the as-of extractor chooses one version per logical bucket.
    unique: list[MetricObservation] = []
    seen: set[tuple[str, object, int | None, str, bool, bool]] = set()
    for item in ordered:
        identity = (
            item.snapshot_id, item.observed_at, item.value, item.quality.value,
            item.synthetic, item.interval_uncertain,
        )
        if identity not in seen:
            unique.append(item)
            seen.add(identity)

    real = tuple(item for item in unique if not item.synthetic)
    usable_count = sum(item.value is not None and item.quality.usable for item in real)
    coverage = usable_count / len(real) if real else 0.0
    segments: list[MetricSegment] = []
    maximum_gap = 0.0
    previous: MetricObservation | None = None
    for current in unique:
        if current.synthetic or current.value is None or not current.quality.usable:
            previous = None
            continue
        if previous is None:
            previous = current
            continue
        elapsed = (current.observed_at - previous.observed_at).total_seconds()
        if elapsed <= 0:
            # Preserve the observation, but equal/reversed instants have no rate.
            previous = current
            continue
        maximum_gap = max(maximum_gap, elapsed)
        delta = current.value - previous.value  # type: ignore[operator]
        trusted = (
            previous.quality.trusted_derivative
            and current.quality.trusted_derivative
            and not current.interval_uncertain
            and not previous.interval_uncertain
        )
        reason = "negative_delta" if delta < 0 else None
        segments.append(MetricSegment(
            previous, current, elapsed, delta, delta / elapsed, trusted, reason
        ))
        # A fall/reset breaks the monotonic chain. The new value can start a later
        # independent segment, but the negative interval is never detector evidence.
        previous = current
    return PreparedSeries(tuple(unique), real, tuple(segments), coverage, maximum_gap)


def linear_fit(observations: tuple[MetricObservation, ...]) -> LinearFit | None:
    points = tuple(item for item in observations if item.value is not None)
    if len(points) < 2:
        return None
    origin = points[0].observed_at
    xs = tuple((item.observed_at - origin).total_seconds() for item in points)
    ys = tuple(float(item.value) for item in points if item.value is not None)
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((value - mean_x) ** 2 for value in xs)
    if denominator <= 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
    intercept = mean_y - slope * mean_x
    residuals = tuple(y - (intercept + slope * x) for x, y in zip(xs, ys))
    residual_sum = sum(value * value for value in residuals)
    total_sum = sum((value - mean_y) ** 2 for value in ys)
    r_squared = 1.0 - residual_sum / total_sum if total_sum > 0 else 1.0
    growth = max(1.0, max(ys) - min(ys))
    return LinearFit(slope, intercept, max(0.0, min(1.0, r_squared)), sqrt(residual_sum / len(ys)) / growth)
