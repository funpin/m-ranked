from __future__ import annotations

from decimal import Decimal

import pytest

from api.errors import BadRequest
from api.findings import (
    FINDING_MIN_INDEX, INTERACTION_NORM_FLOOR, MIN_NORM_SAMPLE, VIEW_NORM_FLOOR,
    index, is_finding, norm, type_bucket,
)
from api.params import encode_scoped_cursor, findings_query, scoped_cursor


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


def _query(**overrides):
    values = {"mode": None, "institution": None, "platform": None, "period": None,
              "types": None, "sort": None, "direction": None, "group": None,
              "q": None, "anomalies": None}
    values.update(overrides)
    return findings_query(**values)


def test_findings_query_defaults() -> None:
    query = _query()
    assert (query.mode, query.institution, query.platform, query.period) == ("all", None, "all", "7d")
    assert (query.types, query.sort, query.direction, query.group) == ((), "interaction_index", "desc", "none")
    assert (query.search, query.anomalies) == ("", "exclude")


def test_findings_query_normalizes_aliases_and_type_order() -> None:
    query = _query(platform="tg", types=["video", "photo", "video"], q="  мгу ")
    assert query.platform == "telegram"
    assert query.types == ("photo", "video")
    assert query.search == "мгу"


@pytest.mark.parametrize("overrides, message", [
    ({"period": "3h"}, "период"),
    ({"platform": "ok"}, "платформа"),
    ({"sort": "erv"}, "сортировка"),
    ({"direction": "up"}, "направление"),
    ({"types": ["gif"]}, "тип"),
    ({"mode": "institution"}, "вуз"),
    ({"mode": "institution", "institution": "0"}, "вуз"),
    ({"mode": "institution", "institution": "12", "group": "institution"}, "группировка"),
    ({"group": "platform"}, "группировка"),
    ({"anomalies": "hide"}, "аномали"),
    ({"q": "a" * 201}, "200"),
])
def test_findings_query_rejects_unknown_values(overrides, message) -> None:
    with pytest.raises(BadRequest) as error:
        _query(**overrides)
    assert message in (error.value.detail or "")


def test_findings_cursor_is_bound_to_every_dimension() -> None:
    query = _query(mode="institution", institution="12", types=["photo"])
    cursor = encode_scoped_cursor("00000000-0000-4000-8000-000000000001", 5, "findings:" + query.dimensions)
    assert scoped_cursor(cursor, 5, "findings:" + query.dimensions)
    changed = _query(mode="institution", institution="12", types=["video"])
    with pytest.raises(BadRequest):
        scoped_cursor(cursor, 5, "findings:" + changed.dimensions)
