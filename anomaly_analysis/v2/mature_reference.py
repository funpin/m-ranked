"""Frozen, platform-specific 72-hour reference. Counts do not identify causes.

Four dependent components share one calibration cutoff. Runtime inference
needs no database query, training, interpolation, or extra metric storage.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any, Mapping
from types import MappingProxyType
from uuid import UUID

from .domain import Family, Interval, Metric, PostSeries, Sign

VERSION = "1.0.0"
PATTERNS = frozenset({11, 12})
HOUR = 3600
METRICS = (Metric.VIEWS, Metric.REACTIONS)
REFERENCES = Path(__file__).with_name("references")
# Every bundled artifact; renewals are added next to the old ones, never replace them:
# stored verdicts keep pointing at the version that produced them.
ARTIFACTS = "max_*.json"


@dataclass(frozen=True, slots=True)
class Endpoints:
    early: tuple[int, int]
    late: tuple[int, int]
    early_at: datetime
    late_at: datetime


def endpoints(series: PostSeries, analyzed_at: datetime) -> tuple[Endpoints | None, str]:
    """Use the last read in each backward window, never last *good* read.

    A more recent unknown/rounded read cannot be replaced by an older exact
    one. Known downward corrections anywhere before 72h also cause abstention.
    Missing intermediate reads do not prevent an endpoint-level comparison.
    """
    if series.is_repost:
        return None, "repost"
    if analyzed_at < series.published_at + timedelta(hours=72):
        return None, "not_mature"
    times = series.observed_at
    values = [series.exact_values(m) for m in METRICS]
    if any(v is None for v in values):
        return None, "missing_metric"
    ages = [(at - series.published_at).total_seconds() for at in times]
    indices = []
    for lower, upper in ((21, 24), (66, 72)):
        candidates = [i for i, age in enumerate(ages) if lower * HOUR <= age <= upper * HOUR]
        if not candidates:
            return None, "missing_window"
        index = candidates[-1]
        if any(v[index] is None for v in values):
            return None, "nonexact_endpoint"
        indices.append(index)
    for column in values:
        maximum = -1
        for i, age in enumerate(ages):
            if not 0 <= age <= 72 * HOUR:
                continue
            value = column[i]
            if value is not None:
                if value < maximum:
                    return None, "known_decrease"
                maximum = value
    a, b = indices
    early, late = tuple(v[a] for v in values), tuple(v[b] for v in values)
    return Endpoints(early, late, times[a], times[b]), "eligible"


@dataclass(frozen=True, slots=True)
class Component:
    conditional: bool
    metric: Metric
    intercept: float
    slope: float
    center: float
    sd: float
    scale: float
    effects: Mapping[UUID, float]

    def prediction(self, account: UUID, early: int) -> float:
        x = (math.log1p(early) - self.center) / self.sd if self.conditional else 0.
        return self.intercept + self.slope * x + self.effects[account]


@dataclass(frozen=True, slots=True)
class MatureReference:
    version: str
    platform: str
    available_at: datetime
    expires_at: datetime
    fit_start: datetime
    calibration_end: datetime
    fit_count: int
    calibration_count: int
    account_counts: Mapping[UUID, int]
    cutoff: float
    components: tuple[Component, ...]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> MatureReference:
        def instant(key):
            value = datetime.fromisoformat(payload[key])
            if value.tzinfo is None:
                raise ValueError("reference dates require timezones")
            return value
        if payload["schema_version"] != VERSION or payload["platform"] != "max":
            raise ValueError("unsupported mature reference")
        accounts = {UUID(a): int(n) for a, n in payload["account_counts"].items()}
        components = tuple(Component(
            bool(c["conditional"]), Metric(c["metric"]),
            *(float(c[k]) for k in ("intercept", "slope", "center", "sd", "scale")),
            MappingProxyType({UUID(a): float(v) for a, v in c["effects"].items()}),
        ) for c in payload["components"])
        expected = [(True, Metric.VIEWS), (True, Metric.REACTIONS),
                    (False, Metric.VIEWS), (False, Metric.REACTIONS)]
        if [(c.conditional, c.metric) for c in components] != expected:
            raise ValueError("reference must contain the four calibrated components")
        for c in components:
            numbers = [c.intercept, c.slope, c.center, c.sd, c.scale, *c.effects.values()]
            if (not all(math.isfinite(n) for n in numbers) or c.sd <= 0 or c.scale < .05
                    or set(c.effects) != set(accounts) or c.slope < 0
                    or (not c.conditional and c.slope != 0)
                    or any(c.prediction(a, 0) < 0 for a in accounts)):
                raise ValueError("invalid reference coefficients")
        ref = cls(payload["reference_version"], payload["platform"], instant("available_at"),
                  instant("expires_at"), instant("fit_start"), instant("calibration_end"),
                  int(payload["fit_count"]), int(payload["calibration_count"]), MappingProxyType(accounts),
                  float(payload["cutoff"]), components)
        if (not ref.fit_start < ref.calibration_end < ref.available_at < ref.expires_at
                or min(ref.fit_count, ref.calibration_count) < 100
                or not accounts or min(accounts.values()) < 5
                or sum(accounts.values()) != ref.fit_count
                or not math.isfinite(ref.cutoff) or ref.cutoff < 0
                or not ref.version):
            raise ValueError("invalid reference scope or calibration")
        return ref

    def detect(self, series: PostSeries, analyzed_at: datetime) -> tuple[Sign, ...]:
        if (series.platform != self.platform or series.account_id not in self.account_counts
                or not self.available_at <= series.published_at < self.expires_at):
            return ()
        point, _ = endpoints(series, analyzed_at)
        if point is None:
            return ()
        selected: dict[int, tuple[float, Sign]] = {}
        for c in self.components:
            j = METRICS.index(c.metric)
            prediction = c.prediction(series.account_id, point.early[j])
            score = (math.log1p(point.late[j]) - prediction) / c.scale
            if score <= self.cutoff:
                continue
            # A valid signed-64-bit counter cannot exceed a larger boundary.
            upper_log = prediction + self.cutoff * c.scale
            if upper_log > math.log1p(2**63 - 1):
                continue
            expected = max(0., math.expm1(prediction))
            upper = max(0, math.floor(math.expm1(upper_log)))
            pattern = 12 if c.conditional else 11
            start = point.early_at if c.conditional else series.published_at
            render = {
                "kind": "reference", "startAge": int((start-series.published_at).total_seconds()),
                "endAge": int((point.late_at-series.published_at).total_seconds()),
                "observed": point.late[j], "expected": round(expected, 2), "upper": upper,
                "early": point.early[j], "fitPosts": self.fit_count,
                "calibrationPosts": self.calibration_count,
                "accountFitPosts": self.account_counts[series.account_id],
                "referenceVersion": self.version, "referenceStart": self.fit_start.isoformat(),
                "referenceEnd": self.calibration_end.isoformat(),
                "measurementMode": "exact_quality_v1",
            }
            formula = (f"Y72={point.late[j]} > {upper} (верхняя целая граница); "
                       f"ожидание={expected:.1f}; "
                       + (f"Y24={point.early[j]}; " if c.conditional else "")
                       + f"общая калибровка четырёх компонент: n={self.calibration_count}")
            sign = Sign(pattern, Family.VELOCITY, c.metric, .5, Interval(start, point.late_at),
                        timedelta(hours=72), formula, render,
                        ("news_event", "forward_by_large_channel", "audience_change"))
            if pattern not in selected or score > selected[pattern][0]:
                selected[pattern] = (score, sign)
        return tuple(selected[p][1] for p in sorted(selected))


    def version_for(self, series: PostSeries) -> str:
        return self.version


@dataclass(frozen=True, slots=True)
class ReferenceSet:
    """Frozen artifacts of one platform. A post uses the newest artifact whose
    scope [available_at, expires_at) covers its publication; overlapping scopes
    let a renewal start before the previous artifact expires."""

    references: tuple[MatureReference, ...]

    def __post_init__(self) -> None:
        if not self.references or len({item.platform for item in self.references}) != 1:
            raise ValueError("a reference set needs artifacts of one platform")
        if len({item.version for item in self.references}) != len(self.references):
            raise ValueError("reference versions must be unique")
        object.__setattr__(self, "references", tuple(sorted(self.references, key=lambda item: item.available_at)))

    @property
    def platform(self) -> str:
        return self.references[0].platform

    @property
    def available_at(self) -> datetime:
        return self.references[0].available_at

    @property
    def expires_at(self) -> datetime:
        return max(item.expires_at for item in self.references)

    @property
    def account_counts(self) -> Mapping[UUID, int]:
        merged: dict[UUID, int] = {}
        for item in self.references:
            merged.update(item.account_counts)
        return MappingProxyType(merged)

    @property
    def version(self) -> str:
        return self.references[-1].version

    def for_post(self, series: PostSeries) -> MatureReference | None:
        return next((item for item in reversed(self.references)
                     if item.available_at <= series.published_at < item.expires_at), None)

    def detect(self, series: PostSeries, analyzed_at: datetime) -> tuple[Sign, ...]:
        reference = self.for_post(series)
        return () if reference is None else reference.detect(series, analyzed_at)

    def version_for(self, series: PostSeries) -> str:
        reference = self.for_post(series)
        return self.version if reference is None else reference.version


def load_references(directory: Path = REFERENCES) -> ReferenceSet:
    return ReferenceSet(tuple(MatureReference.from_payload(json.loads(path.read_text(encoding="utf-8")))
                              for path in sorted(directory.glob(ARTIFACTS))))


@lru_cache(maxsize=1)
def bundled_reference() -> ReferenceSet:
    """Fail clearly at startup if a release artifact is absent or corrupt."""
    return load_references()
