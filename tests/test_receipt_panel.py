from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from anomaly_analysis.neighbor_exposure import PublishedPost, SuccessfulRead
from anomaly_analysis.v2.receipt_panel import consecutive_growth

ACCOUNT = UUID("30000000-0000-4000-8000-000000000001")
POST = UUID("30000000-0000-4000-8000-000000000002")
PUBLISHED = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
FIRST = PUBLISHED + timedelta(days=2)
POST_META = (PublishedPost(POST, ACCOUNT, PUBLISHED),)
PLATFORM = {ACCOUNT: "max"}
GAP = {"max": timedelta(minutes=30)}


def read(minutes: int, views: int | None, quality: str = "exact", *, uncertain: bool = False):
    return SuccessfulRead(POST, ACCOUNT, FIRST + timedelta(minutes=minutes), views, quality, uncertain)


def test_only_consecutive_successful_reads_define_growth_and_exact_zero() -> None:
    rows = consecutive_growth(
        (read(0, 100), read(15, 100), read(30, 120)), POST_META, PLATFORM,
        max_gap_by_platform=GAP,
    )
    assert [(row.displayed_delta_views, row.status, row.exact_zero_observed) for row in rows] == [
        (0, "usable", True), (20, "usable", False),
    ]
    assert rows[0].age_seconds == 2 * 86400
    assert rows[1].log_growth is not None
    assert consecutive_growth((read(0, 100),), POST_META, PLATFORM, max_gap_by_platform=GAP) == ()


def test_rounded_zero_and_missing_or_long_intervals_do_not_become_exact_zeros() -> None:
    rounded = consecutive_growth((read(0, 100, "rounded"), read(15, 100, "rounded")),
                                 POST_META, PLATFORM, max_gap_by_platform=GAP)[0]
    missing = consecutive_growth((read(0, 100), read(15, None)),
                                 POST_META, PLATFORM, max_gap_by_platform=GAP)[0]
    gap = consecutive_growth((read(0, 100), read(60, 100)),
                             POST_META, PLATFORM, max_gap_by_platform=GAP)[0]
    assert rounded.usable and rounded.rounded and not rounded.exact_zero_observed
    assert missing.status == "missing_views" and missing.log_growth is None
    assert gap.status == "excessive_gap" and not gap.exact_zero_observed


def test_correction_and_unknown_platform_abstain() -> None:
    corrected = consecutive_growth((read(0, 100), read(15, 90)),
                                   POST_META, PLATFORM, max_gap_by_platform=GAP)[0]
    assert corrected.status == "negative_correction_or_reset"
    with pytest.raises(ValueError, match="platform-specific"):
        consecutive_growth((read(0, 100), read(15, 120)), POST_META, PLATFORM,
                           max_gap_by_platform={"telegram": timedelta(minutes=30)})
