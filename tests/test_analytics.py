from datetime import datetime, timedelta, timezone

from app.analytics import (
    age_seconds,
    delta_by_reaction,
    history_is_complete,
    hourly_asof_points,
    hourly_bucket,
    interval_uncertain,
    is_spike,
    fixed_cohort_median_curve,
)


def test_calculation_age_uses_utc_and_never_negative():
    published = datetime(2026, 8, 27, 14, 17, 32, tzinfo=timezone.utc)
    measured = published + timedelta(hours=1, minutes=5, seconds=28)
    assert age_seconds(published, measured) == 3928
    assert age_seconds(published, published - timedelta(seconds=5)) == 0


def test_negative_delta_and_per_reaction_delta():
    assert delta_by_reaction({"👍": 10, "❤️": 2}, {"👍": 12, "🔥": 1}) == {
        "❤️": 2, "👍": -2, "🔥": -1
    }


def test_spike_detection_rule_is_explainable():
    assert is_spike(6, 57, 15, 2.0)
    assert not is_spike(45, 60, 15, 2.0)
    assert not is_spike(6, 20, 15, 2.0)


def test_hourly_bucket_keeps_raw_age_separate():
    assert hourly_bucket(3600 + 7 * 60) == 1
    assert hourly_bucket(3599) == 0


def test_missing_measurement_interval_is_uncertain_not_interpolated():
    assert interval_uncertain(5 * 3600, expected_minutes=60)
    assert not interval_uncertain(65 * 60, expected_minutes=60)


def test_complete_partial_classification():
    assert history_is_complete(90 * 60, 90)
    assert not history_is_complete(90 * 60 + 1, 90)


def test_hourly_asof_points_never_uses_a_future_measurement():
    rows = [
        {"age_seconds": 0, "total_reactions": 0},
        {"age_seconds": 50 * 60, "total_reactions": 8},
        {"age_seconds": 70 * 60, "total_reactions": 12},
        {"age_seconds": 3 * 3600, "total_reactions": 20},
    ]
    assert hourly_asof_points(rows, 3) == {0: 0.0, 1: 8.0, 2: 12.0, 3: 20.0}


def test_fixed_cohort_does_not_change_between_hours():
    complete = {0: 0, 1: 10, 2: 20, 3: 30}
    ends_early = {0: 0, 1: 100, 2: 200}
    starts_late = {1: 5, 2: 10, 3: 15}
    curve, counts, cohort_size = fixed_cohort_median_curve(
        [complete, ends_early, starts_late], 3,
    )
    assert curve == [0, 10, 20, 30]
    assert counts == [1, 1, 1, 1]
    assert cohort_size == 1


def test_fixed_cohort_median_can_be_fractional_for_even_post_count():
    curve, counts, cohort_size = fixed_cohort_median_curve(
        [{0: 0, 1: 10}, {0: 0, 1: 11}], 1,
    )
    assert curve == [0.0, 10.5]
    assert counts == [2, 2]
    assert cohort_size == 2
