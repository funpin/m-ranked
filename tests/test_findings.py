from __future__ import annotations

from decimal import Decimal

from api.findings import (
    FINDING_MIN_INDEX, INTERACTION_NORM_FLOOR, MIN_NORM_SAMPLE, VIEW_NORM_FLOOR,
    index, is_finding, norm, type_bucket,
)


def test_norm_is_median_of_known_values_with_sample_size() -> None:
    assert norm([1, 3, None, 5]) == (Decimal("3"), 3)
    assert norm([2, 4]) == (Decimal("3"), 2)
    assert norm([None, None]) == (None, 0)


def test_index_needs_min_sample_and_floors_the_norm() -> None:
    ten = MIN_NORM_SAMPLE
    assert index(20, Decimal("10"), ten, INTERACTION_NORM_FLOOR) == Decimal("2")
    # Норма 2 ниже ограничения 5: делим на 5, а не на 2.
    assert index(10, Decimal("2"), ten, INTERACTION_NORM_FLOOR) == Decimal("2")
    assert index(100, Decimal("20"), ten, VIEW_NORM_FLOOR) == Decimal("2")
    assert index(20, Decimal("10"), ten - 1, INTERACTION_NORM_FLOOR) is None
    assert index(None, Decimal("10"), ten, INTERACTION_NORM_FLOOR) is None
    assert index(0, Decimal("10"), ten, INTERACTION_NORM_FLOOR) == Decimal("0")


def test_finding_threshold_needs_index_and_absolute_interactions() -> None:
    assert is_finding(FINDING_MIN_INDEX, 10)
    assert not is_finding(Decimal("1.49"), 100)
    assert not is_finding(Decimal("9"), 9)
    assert not is_finding(None, 100)
    assert not is_finding(Decimal("2"), None)


def test_publication_types_fold_into_five_buckets() -> None:
    assert [type_bucket(value) for value in ("text", "photo", "album", "video")] == [
        "text", "photo", "album", "video"]
    assert type_bucket("poll") == "other"
    assert type_bucket("share") == "other"
