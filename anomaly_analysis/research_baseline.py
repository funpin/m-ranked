"""Small, offline fixed-age baseline for research calibration.

This module does not publish findings. It deliberately needs only bounded,
already corrected per-post features and the Python standard library. The
account and format effects are shrunk toward their platform cohort; an
independent calibration slice supplies empirical tail ranks.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import log1p
from statistics import median
from typing import Iterable


@dataclass(frozen=True, slots=True)
class FixedAgePost:
    platform: str
    account_id: str
    publication_format: str
    views: int
    reactions: int

    def __post_init__(self) -> None:
        if self.views <= 0 or self.reactions < 0:
            raise ValueError("fixed-age counts must have positive views and nonnegative reactions")

    @property
    def log_views(self) -> float:
        return log1p(self.views)

    @property
    def log_reaction_rate(self) -> float:
        return log1p(self.reactions) - log1p(self.views)


@dataclass(frozen=True, slots=True)
class Prediction:
    predicted_log_views: float
    predicted_log_reaction_rate: float
    views_residual: float
    reactions_residual: float
    combined_score: float


@dataclass(frozen=True, slots=True)
class _Component:
    center: float
    account_effects: dict[str, float]
    format_effects: dict[str, float]
    scale: float

    def predict(self, row: FixedAgePost) -> float:
        return (self.center + self.account_effects.get(row.account_id, 0.0)
                + self.format_effects.get(row.publication_format, 0.0))


class RobustPlatformBaseline:
    def __init__(self, platform: str, views: _Component, reactions: _Component):
        self.platform = platform
        self.views = views
        self.reactions = reactions

    @classmethod
    def fit(cls, platform: str, rows: Iterable[FixedAgePost]) -> "RobustPlatformBaseline":
        selected = tuple(row for row in rows if row.platform == platform)
        if len(selected) < 20 or len({row.account_id for row in selected}) < 2:
            raise ValueError("at least 20 posts from two accounts are required")
        return cls(
            platform,
            _fit_component(selected, lambda row: row.log_views),
            _fit_component(selected, lambda row: row.log_reaction_rate),
        )

    def predict(self, row: FixedAgePost) -> Prediction:
        if row.platform != self.platform:
            raise ValueError("platform mismatch")
        expected_v = self.views.predict(row)
        expected_r = self.reactions.predict(row)
        z_v = (row.log_views - expected_v) / self.views.scale
        z_r = (row.log_reaction_rate - expected_r) / self.reactions.scale
        return Prediction(expected_v, expected_r, z_v, z_r, max(abs(z_v), abs(z_r)))


def _fit_component(rows: tuple[FixedAgePost, ...], value) -> _Component:
    center = median(value(row) for row in rows)
    by_account: dict[str, list[float]] = {}
    for row in rows:
        by_account.setdefault(row.account_id, []).append(value(row))
    account_effects = {
        account: len(values) / (len(values) + 8) * (median(values) - center)
        for account, values in by_account.items()
    }
    by_format: dict[str, list[float]] = {}
    for row in rows:
        by_format.setdefault(row.publication_format, []).append(
            value(row) - center - account_effects[row.account_id]
        )
    format_effects = {
        publication_format: len(values) / (len(values) + 20) * median(values)
        for publication_format, values in by_format.items()
    }
    errors = [abs(value(row) - center - account_effects[row.account_id]
                  - format_effects[row.publication_format]) for row in rows]
    # This is only a robust score scale. The empirical calibration slice,
    # rather than a Gaussian/NB tail assumption, determines the p-rank.
    scale = max(0.2, 1.4826 * median(errors))
    return _Component(center, account_effects, format_effects, scale)


def empirical_upper_tail(score: float, calibration_scores: Iterable[float]) -> float:
    values = tuple(calibration_scores)
    if not values:
        raise ValueError("calibration set is empty")
    return (1 + sum(value >= score for value in values)) / (len(values) + 1)
