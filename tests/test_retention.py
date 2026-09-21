"""Working-set retention policy, disk watermarks and profile guards."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from collector_target.retention import (
    PAUSE_COLLECTION_DISK_PERCENT,
    STOP_BACKFILL_DISK_PERCENT,
    WARN_DISK_PERCENT,
    DiskState,
    RetentionOutcome,
    RetentionPolicy,
    RetentionRefused,
    WorkingSetRetention,
)


class _Repository:
    def __init__(self, profile: str = "b") -> None:
        self.deployment_profile = profile


def test_retention_is_refused_outside_profile_b() -> None:
    """In profile A this database is the product, not a buffer."""
    with pytest.raises(RetentionRefused, match="profile b"):
        WorkingSetRetention(_Repository("a"), RetentionPolicy(mode="on"))


def test_retention_disabled_is_allowed_in_either_profile() -> None:
    # Constructing the object must not require profile B; only running does.
    for profile in ("a", "b"):
        retention = WorkingSetRetention(
            _Repository(profile), RetentionPolicy(mode="off"),
        )
        assert retention.run() == RetentionOutcome((), (), None, False)


@pytest.mark.parametrize("mode", ["", "enabled", "yes", "ON "])
def test_unknown_retention_mode_is_rejected(mode: str) -> None:
    with pytest.raises(ValueError, match="off, dry-run or on"):
        RetentionPolicy(mode=mode)


@pytest.mark.parametrize(
    ("field", "value"),
    [("track_post_for_hours", 0), ("months_per_run", 0), ("months_per_run", -1)],
)
def test_nonpositive_policy_values_are_rejected(field: str, value: int) -> None:
    with pytest.raises(ValueError):
        RetentionPolicy(mode="on", **{field: value})


def test_default_policy_is_off_so_nothing_is_released_by_accident() -> None:
    policy = RetentionPolicy()
    assert policy.mode == "off"
    assert not policy.enabled
    assert policy.track_post_for_hours == 960


@pytest.mark.parametrize(
    ("used", "warns", "stops", "pauses", "threshold"),
    [
        (10.0, False, False, False, "ok"),
        (WARN_DISK_PERCENT, True, False, False, "warn"),
        (STOP_BACKFILL_DISK_PERCENT, True, True, False, "stop_backfill"),
        (PAUSE_COLLECTION_DISK_PERCENT, True, True, True, "pause_collection"),
        (99.9, True, True, True, "pause_collection"),
    ],
)
def test_disk_watermarks_are_inclusive_and_ordered(
    used: float, warns: bool, stops: bool, pauses: bool, threshold: str,
) -> None:
    state = DiskState(used, 1024)
    assert state.warns is warns
    assert state.stops_backfill is stops
    assert state.pauses_collection is pauses
    assert state.threshold == threshold


def test_outcome_counts_match_their_month_lists() -> None:
    outcome = RetentionOutcome(
        (date(2026, 1, 1), date(2026, 2, 1)), (date(2026, 3, 1),),
        date(2026, 3, 1), False,
    )
    assert outcome.released == 2
    assert outcome.deferred == 1
