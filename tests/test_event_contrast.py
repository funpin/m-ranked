from datetime import datetime, timedelta, timezone
from uuid import UUID

from anomaly_analysis.neighbor_exposure import PublishedPost
from anomaly_analysis.v2.event_contrast import event_contrast
from anomaly_analysis.v2.receipt_panel import ObservedGrowth

ACCOUNT = UUID("40000000-0000-4000-8000-000000000001")
OLDER_1 = UUID("40000000-0000-4000-8000-000000000002")
OLDER_2 = UUID("40000000-0000-4000-8000-000000000003")
TARGET = UUID("40000000-0000-4000-8000-000000000004")
NEW = UUID("40000000-0000-4000-8000-000000000005")
BASE = datetime(2026, 9, 14, 15, tzinfo=timezone.utc)
ORDER = tuple(PublishedPost(pid, ACCOUNT, BASE - timedelta(days=days))
              for pid, days in ((OLDER_1, 4), (OLDER_2, 3), (TARGET, 2))) + (
                  PublishedPost(NEW, ACCOUNT, BASE + timedelta(minutes=3)),)


def interval(post: UUID, start: datetime, delta: int, *, rounded: bool = False,
             status: str = "usable") -> ObservedGrowth:
    return ObservedGrowth("telegram", ACCOUNT, post, start, start + timedelta(minutes=15),
                          172800, 900, 1000, 1000 + delta, delta, 0.0 if status == "usable" else None,
                          rounded, delta == 0 and not rounded, status)


def sample():
    event = [interval(TARGET, BASE, 100), interval(OLDER_1, BASE, 50),
             interval(OLDER_2, BASE, 40)]
    quiet_at = BASE - timedelta(hours=5)
    histories = {post: (interval(post, quiet_at, 10),) for post in (TARGET, OLDER_1, OLDER_2)}
    return event, histories


def test_event_contrast_uses_actual_same_post_quiet_intervals_and_two_older_peers():
    events, histories = sample()
    result = event_contrast(events[0], events[1:], histories, ORDER, complete_order=True)
    assert result.status == "contrast_available"
    assert result.event_publication_ids == (NEW,)
    assert (result.target_extra_per_hour, result.peer_extra_median_per_hour,
            result.residual_per_hour, result.matched_peer_count) == (360, 140, 220, 2)


def test_missing_exposure_or_control_abstains_instead_of_claiming_normality():
    events, histories = sample()
    assert event_contrast(events[0], events[1:], histories, ORDER, complete_order=False).reason == \
        "incomplete_publication_order"
    assert event_contrast(events[0], events[1:], histories, ORDER[:-1], complete_order=True).reason == \
        "no_nearby_new_post"
    assert event_contrast(events[0], events[1:], {}, ORDER, complete_order=True).reason == \
        "no_target_quiet_control"
    result = event_contrast(events[0], events[1:], {TARGET: histories[TARGET]}, ORDER,
                            complete_order=True)
    assert result.status == "insufficient_data" and result.matched_peer_count == 0


def test_rounded_and_unusable_reads_are_not_silently_treated_as_exact():
    events, histories = sample()
    histories[OLDER_1] = (interval(OLDER_1, BASE - timedelta(hours=5), 10, rounded=True),)
    result = event_contrast(events[0], events[1:], histories, ORDER, complete_order=True)
    assert result.status == "contrast_available" and result.rounded
    unusable = interval(TARGET, BASE, -5, status="negative_correction_or_reset")
    assert event_contrast(unusable, events[1:], histories, ORDER,
                          complete_order=True).reason == "unusable_target_interval"
