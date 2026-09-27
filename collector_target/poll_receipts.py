"""Bounded research cohort for successful per-publication reads.

The normal snapshot stream records changes and sparse heartbeats. A receipt
records an actual successful read, including an unchanged counter. No receipt
outside the explicitly selected cohort means unknown, never zero growth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from .model import CanonicalPublication


def parse_account_ids(raw: str, *, name: str) -> tuple[UUID, ...]:
    if not raw.strip():
        return ()
    try:
        values = tuple(UUID(part.strip()) for part in raw.split(","))
    except ValueError as error:
        raise ValueError(f"{name} must be comma-separated UUIDs") from error
    if len(values) > 16 or len(set(values)) != len(values):
        raise ValueError(f"{name} must contain at most 16 unique account IDs")
    return values


@dataclass(frozen=True, slots=True)
class PollReceiptPolicy:
    account_ids: frozenset[UUID] = frozenset()
    max_post_age: timedelta = timedelta(days=7)
    cadence: timedelta = timedelta(minutes=15)
    retention: timedelta = timedelta(days=7)
    max_posts_per_batch: int = 16
    prune_batch_size: int = 1000

    def __post_init__(self) -> None:
        if len(self.account_ids) > 16:
            raise ValueError("poll receipt cohort is limited to 16 accounts")
        if not timedelta(hours=1) <= self.max_post_age <= timedelta(days=14):
            raise ValueError("poll receipt post age must be within 1 hour and 14 days")
        if not timedelta(minutes=5) <= self.cadence <= timedelta(hours=1):
            raise ValueError("poll receipt cadence must be within 5 and 60 minutes")
        if not timedelta(days=1) <= self.retention <= timedelta(days=14):
            raise ValueError("poll receipt retention must be within 1 and 14 days")
        if not 1 <= self.max_posts_per_batch <= 16 or not 1 <= self.prune_batch_size <= 1000:
            raise ValueError("poll receipt batch limits are invalid")

    @property
    def enabled(self) -> bool:
        return bool(self.account_ids)

    def select(
        self, account_id: UUID, publications: tuple[CanonicalPublication, ...],
    ) -> tuple[CanonicalPublication, ...]:
        if account_id not in self.account_ids:
            return ()
        eligible = [
            item for item in publications
            if not item.snapshot.synthetic
            and 0 <= item.snapshot.age_seconds <= self.max_post_age.total_seconds()
        ]
        eligible.sort(
            key=lambda item: (item.published_at, item.snapshot.observed_at, item.id),
            reverse=True,
        )
        seen: set[UUID] = set()
        selected: list[CanonicalPublication] = []
        for item in eligible:
            if item.id in seen:
                continue
            seen.add(item.id)
            selected.append(item)
            if len(selected) >= self.max_posts_per_batch:
                break
        return tuple(selected)

    def bucket(self, publication: CanonicalPublication) -> int:
        return int(publication.snapshot.observed_at.timestamp()) // int(self.cadence.total_seconds())
