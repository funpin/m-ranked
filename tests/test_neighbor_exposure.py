from datetime import datetime, timedelta, timezone
from uuid import UUID

from anomaly_analysis.neighbor_exposure import (
    PublishedPost, SuccessfulRead, interval_for_reads,
)

ACCOUNT = UUID("10000000-0000-4000-8000-000000000001")
OTHER = UUID("10000000-0000-4000-8000-000000000002")
OLD = UUID("20000000-0000-4000-8000-000000000001")
NEW = UUID("20000000-0000-4000-8000-000000000002")


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 9, 14, hour, minute, tzinfo=timezone.utc)


def test_near_post_release_is_context_for_a_real_read_interval():
    before = SuccessfulRead(OLD, ACCOUNT, at(12, 3), 2800, "rounded")
    after = SuccessfulRead(OLD, ACCOUNT, at(12, 28), 2900, "rounded")
    posts = (PublishedPost(OLD, ACCOUNT, at(10, 0)),
             PublishedPost(NEW, ACCOUNT, at(12, 21)),
             PublishedPost(UUID("20000000-0000-4000-8000-000000000003"), OTHER, at(12, 21)))

    interval = interval_for_reads(before, after, posts,
                                  max_gap=timedelta(hours=2), complete_order=True)

    assert interval.status == "usable"
    assert interval.displayed_delta_views == 100
    assert interval.event_publication_ids == (NEW,)
    assert interval.nearest_event_distance == 1
    assert interval.requires_event_conditioning
    assert not interval.exact_zero_observed
    incomplete = interval_for_reads(before, after, posts,
                                    max_gap=timedelta(hours=2), complete_order=False)
    assert not incomplete.requires_event_conditioning
    assert incomplete.status == "incomplete_publication_order"


def test_only_exact_successive_reads_can_establish_a_zero():
    posts = (PublishedPost(OLD, ACCOUNT, at(10, 0)),)
    before = SuccessfulRead(OLD, ACCOUNT, at(12, 0), 42, "exact")
    unchanged = SuccessfulRead(OLD, ACCOUNT, at(12, 15), 42, "exact")
    rounded = SuccessfulRead(OLD, ACCOUNT, at(12, 15), 42, "rounded")
    exact_interval = interval_for_reads(before, unchanged, posts,
                                        max_gap=timedelta(hours=1), complete_order=True)
    rounded_interval = interval_for_reads(before, rounded, posts,
                                          max_gap=timedelta(hours=1), complete_order=True)
    assert exact_interval.exact_zero_observed
    assert not rounded_interval.exact_zero_observed
    assert interval_for_reads(before, unchanged, posts, max_gap=timedelta(minutes=5),
                              complete_order=True).status == "excessive_gap"


def test_fourth_following_post_is_still_a_neighbor_event():
    before = SuccessfulRead(OLD, ACCOUNT, datetime(2026, 9, 15, 9, 17, tzinfo=timezone.utc),
                            3630, "rounded")
    after = SuccessfulRead(OLD, ACCOUNT, datetime(2026, 9, 15, 10, 22, tzinfo=timezone.utc),
                           3690, "rounded")
    posts = [PublishedPost(OLD, ACCOUNT, at(10, 0))]
    for number in range(2, 6):
        posts.append(PublishedPost(UUID(f"20000000-0000-4000-8000-{number:012d}"),
                                   ACCOUNT, datetime(2026, 9, 14, 13 + number, 0,
                                                     tzinfo=timezone.utc)))
    fourth = UUID("20000000-0000-4000-8000-000000000005")
    posts[-1] = PublishedPost(fourth, ACCOUNT,
                              datetime(2026, 9, 15, 10, 1, tzinfo=timezone.utc))
    interval = interval_for_reads(before, after, tuple(posts),
                                  max_gap=timedelta(hours=2), complete_order=True)
    assert interval.event_publication_ids == (fourth,)
    assert interval.nearest_event_distance == 4
