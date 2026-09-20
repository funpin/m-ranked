"""Canonical metric capabilities used by publication statistics.

The matrix follows the collector contracts: a structurally unsupported
interaction component contributes zero, while a missing supported component
makes the interaction total unknown.
"""
from __future__ import annotations

from decimal import Decimal
from statistics import median
from typing import Iterable

PLATFORM_METRIC_CAPABILITIES: dict[str, frozenset[str]] = {
    "telegram": frozenset({"views", "reactions", "comments"}),
    "vk": frozenset({"views", "reactions", "comments", "shares"}),
    "max": frozenset({"views", "reactions"}),
    "rutube": frozenset({"views", "reactions", "comments"}),
}

INTERACTION_COMPONENTS = ("reactions", "comments", "shares")


def supports(platform: str, metric: str) -> bool:
    return metric in PLATFORM_METRIC_CAPABILITIES[platform]


def interactions(platform: str, reactions: int | None, comments: int | None,
                 shares: int | None) -> int | None:
    values = {"reactions": reactions, "comments": comments, "shares": shares}
    supported = PLATFORM_METRIC_CAPABILITIES[platform]
    if any(values[metric] is None for metric in INTERACTION_COMPONENTS if metric in supported):
        return None
    return sum(values[metric] or 0 for metric in INTERACTION_COMPONENTS if metric in supported)


def publication_erv(interaction_count: int | None, views: int | None) -> Decimal | None:
    if interaction_count is None or views is None or views <= 0:
        return None
    return Decimal(interaction_count) * Decimal(100) / Decimal(views)


def aggregate_statistics(samples: Iterable[tuple[int | None, int | None]]) -> dict[str, object]:
    """Small reference implementation used to pin SQL aggregate semantics."""
    values = list(samples)
    known_interactions = [value for value, _views in values if value is not None]
    known_views = [views for _value, views in values if views is not None]
    eligible = [(value, views) for value, views in values
                if value is not None and views is not None and views > 0]
    numerator = sum(value for value, _views in eligible)
    denominator = sum(views for _value, views in eligible)
    return {
        "publicationCount": len(values),
        "interactionSampleSize": len(known_interactions),
        "viewSampleSize": len(known_views),
        "ervSampleSize": len(eligible),
        "medianInteractions": Decimal(str(median(known_interactions))) if known_interactions else None,
        "interactions": sum(known_interactions) if known_interactions else None,
        "views": sum(known_views) if known_views else None,
        "erv": (Decimal(numerator) * Decimal(100) / Decimal(denominator)
                if denominator > 0 else None),
    }


def sql_values() -> str:
    rows = []
    for platform, metrics in PLATFORM_METRIC_CAPABILITIES.items():
        flags = ",".join("true" if metric in metrics else "false"
                         for metric in INTERACTION_COMPONENTS)
        rows.append(f"('{platform}',{flags})")
    return ",\n        ".join(rows)
