"""Working-set retention for a profile B collector host.

Server 1 keeps only what the adapters need to plan the next cycle; the full
history lives on Server 2.

Depth is trimmed by whole monthly partitions rather than by row, because
observations are append-only: ``ingest.observation_immutable`` refuses a
``DELETE`` outright.  That invariant is deliberate, so retention follows the
same route the cold archive already takes — detach and drop a partition — and
only differs in what it accepts as proof that the data survives elsewhere.  For
the cold archive that proof is a verified export manifest; here it is Server 2
having acknowledged every batch that covers the month.

A consequence worth stating plainly: a publication still inside the tracking
window keeps **all** of its observations.  There is no way to thin a live
publication's history without breaking append-only, so this module does not try.
That also means ``metric_ever_positive`` and its window of 24 observations are
untouched by retention.

Nothing is removed before Server 2 has acknowledged it.  No disk pressure
changes that: at the last watermark the right move is to stop and page a human,
not to buy space with data nobody else holds yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import logging
import shutil
from typing import Any

from .normalize import sanitize_error_code


logger = logging.getLogger(__name__)

WARN_DISK_PERCENT = 70
STOP_BACKFILL_DISK_PERCENT = 80
PAUSE_COLLECTION_DISK_PERCENT = 90


class RetentionRefused(RuntimeError):
    """Retention was asked to run where it would destroy served data."""


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    mode: str = "off"
    track_post_for_hours: int = 720
    months_per_run: int = 1

    def __post_init__(self) -> None:
        if self.mode not in {"off", "dry-run", "on"}:
            raise ValueError(
                "COLLECTOR_WORKING_SET_RETENTION must be off, dry-run or on"
            )
        if self.track_post_for_hours < 1:
            raise ValueError("track_post_for_hours must be positive")
        if self.months_per_run < 1:
            raise ValueError("months_per_run must be positive")

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    @property
    def dry_run(self) -> bool:
        return self.mode == "dry-run"


@dataclass(frozen=True, slots=True)
class RetentionOutcome:
    released_months: tuple[date, ...]
    deferred_months: tuple[date, ...]
    oldest_retained_month: date | None
    dry_run: bool

    @property
    def released(self) -> int:
        return len(self.released_months)

    @property
    def deferred(self) -> int:
        return len(self.deferred_months)


@dataclass(frozen=True, slots=True)
class DiskState:
    used_percent: float
    free_bytes: int

    @property
    def pauses_collection(self) -> bool:
        return self.used_percent >= PAUSE_COLLECTION_DISK_PERCENT

    @property
    def stops_backfill(self) -> bool:
        return self.used_percent >= STOP_BACKFILL_DISK_PERCENT

    @property
    def warns(self) -> bool:
        return self.used_percent >= WARN_DISK_PERCENT

    @property
    def threshold(self) -> str:
        if self.pauses_collection:
            return "pause_collection"
        if self.stops_backfill:
            return "stop_backfill"
        if self.warns:
            return "warn"
        return "ok"


def disk_state(path: str) -> DiskState:
    usage = shutil.disk_usage(path)
    used = 100.0 * (usage.total - usage.free) / usage.total if usage.total else 0.0
    return DiskState(used, usage.free)


def _row(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    return row[index]


class WorkingSetRetention:
    """Release whole observation months that Server 2 already holds."""

    def __init__(
        self,
        repository: Any,
        policy: RetentionPolicy,
        *,
        clock: Any = None,
        metrics: Any = None,
    ) -> None:
        if policy.enabled and getattr(repository, "deployment_profile", "a") != "b":
            # In profile A this database is the product. Trimming it would not
            # relieve a second host of anything; it would delete what the API
            # serves.
            raise RetentionRefused(
                "working set retention is only available in deployment profile b"
            )
        self.repository = repository
        self.policy = policy
        self.clock = clock
        self.metrics = metrics

    def _now(self) -> datetime:
        return (
            self.clock.now() if self.clock is not None
            else datetime.now(timezone.utc)
        )

    def candidate_months(self, connection: Any) -> tuple[tuple[date, bool], ...]:
        """Every stored month with whether it may be released right now."""
        rows = connection.execute(
            """SELECT months.published_month,
                      ops_and_admin.collector_working_set_month_releasable(
                          months.published_month, %s
                      ) AS releasable
                 FROM (
                     SELECT DISTINCT published_month
                       FROM ingest.publication_metric_snapshot
                 ) AS months
                ORDER BY months.published_month""",
            (self.policy.track_post_for_hours,),
        ).fetchall()
        return tuple(
            (_row(item, "published_month", 0), bool(_row(item, "releasable", 1)))
            for item in rows
        )

    def run(self) -> RetentionOutcome:
        if not self.policy.enabled:
            return RetentionOutcome((), (), None, False)
        try:
            outcome = self._run()
        except Exception as error:
            logger.error(
                "working set retention failed code=%s", sanitize_error_code(error),
            )
            raise
        self._observe(outcome)
        logger.info(
            "working set retention completed released=%s deferred=%s dry_run=%s",
            outcome.released, outcome.deferred, outcome.dry_run,
        )
        return outcome

    def _run(self) -> RetentionOutcome:
        with self.repository._connection() as connection:
            candidates = self.candidate_months(connection)
        releasable = [month for month, allowed in candidates if allowed]
        deferred = tuple(month for month, allowed in candidates if not allowed)
        selected = tuple(releasable[: self.policy.months_per_run])
        oldest = min((month for month, _ in candidates), default=None)

        if self.policy.dry_run:
            return RetentionOutcome(selected, deferred, oldest, True)

        released: list[date] = []
        for month in selected:
            with (
                self.repository._connection() as connection,
                connection.transaction(),
            ):
                # The profile is asserted inside the function as well; setting
                # it here is what makes that assertion true for this session.
                connection.execute(
                    "SELECT set_config('mranked.deployment_profile', %s, true)",
                    (getattr(self.repository, "deployment_profile", "a"),),
                )
                row = connection.execute(
                    """SELECT ops_and_admin.drop_collector_working_set_month(%s, %s)
                           AS dropped""",
                    (month, self.policy.track_post_for_hours),
                ).fetchone()
            if row is not None and bool(_row(row, "dropped", 0)):
                released.append(month)

        with self.repository._connection() as connection:
            remaining = connection.execute(
                """SELECT min(published_month) AS oldest
                     FROM ingest.publication_metric_snapshot""",
            ).fetchone()
            oldest = _row(remaining, "oldest", 0) if remaining is not None else None
        return RetentionOutcome(tuple(released), deferred, oldest, False)

    def _observe(self, outcome: RetentionOutcome) -> None:
        if self.metrics is None:
            return
        try:
            self.metrics.working_set(
                released_months=outcome.released,
                deferred_months=outcome.deferred,
                oldest_retained_month=outcome.oldest_retained_month,
            )
        except Exception as error:
            logger.warning(
                "retention metrics unavailable code=%s", sanitize_error_code(error),
            )
