from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from api import dto
from api.errors import BadRequest, NotFound
from api.findings import (
    FINDING_MIN_INDEX, INTERACTION_NORM_FLOOR, MIN_NORM_SAMPLE, VIEW_NORM_FLOOR,
    index, is_finding, norm, type_bucket,
)
from api.routes.findings import findings_body
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


def _row(number: int, institution: int = 1, **overrides) -> dict:
    row = {
        "publication_id": f"00000000-0000-4000-8000-{number:012d}",
        "institution_id": f"00000000-0000-4000-9000-{institution:012d}",
        "institution_legacy_id": institution, "institution_short_name": f"В{institution}",
        "institution_canonical_name": f"Вуз {institution}",
        "account_id": "00000000-0000-4000-a000-000000000001", "platform": "vk",
        "publication_type": "photo", "external_id": f"-1_{number}", "public_url": None,
        "published_at": datetime(2026, 9, 26, tzinfo=timezone.utc), "age_hours": 24,
        "preliminary": False, "interaction_index": Decimal("2.5"), "view_index": Decimal("1.2"),
        "interaction_norm": 20.0, "view_norm": 1000.0, "norm_sample": 12, "interactions": 50,
        "reactions": 40, "comments": 10, "shares": None, "views": 1200, "erv": Decimal("4.1666"),
        "level": None, "rank": number, "institution_rank": number,
        "institution_finding_count": 3, "total": 3, "hidden_anomalous": 2,
    }
    row.update(overrides)
    return row


def test_finding_dto_keeps_unknown_distinct_from_zero() -> None:
    result = dto.finding(_row(1, interactions=0, interaction_index=Decimal("0"), level=1))
    assert result["interactions"] == 0 and result["interactionIndex"] == 0.0
    assert result["anomalyLevel"] == 1 and result["publicationType"] == "photo"
    assert result["capabilities"] == {"reactions": True, "comments": True, "shares": True}
    unknown = dto.finding(_row(1, interactions=None, interaction_index=None, age_hours=None))
    assert unknown["interactions"] is None and unknown["interactionIndex"] is None
    assert unknown["ageHours"] is None


def test_findings_body_pages_list_and_reports_summary() -> None:
    query = _query()
    rows = [_row(number) for number in (1, 2, 3)]
    body = findings_body(query, rows, [], 2, None, 9, datetime(2026, 9, 27, tzinfo=timezone.utc), "d")
    assert [item["externalId"] for item in body["items"]] == ["-1_1", "-1_2"]
    assert body["hasMore"] is True and body["nextCursor"]
    assert (body["total"], body["hiddenAnomalous"], body["groups"]) == (3, 2, [])


def test_findings_body_groups_by_institution_in_rank_order() -> None:
    query = _query(group="institution")
    rows = [_row(1, 2), _row(2, 1), _row(3, 2, institution_rank=2)]
    body = findings_body(query, rows, [], 50, None, 9, datetime(2026, 9, 27, tzinfo=timezone.utc), "d")
    assert [group["institutionLegacyId"] for group in body["groups"]] == [2, 1]
    assert [len(group["items"]) for group in body["groups"]] == [2, 1]
    assert body["items"] == [] and body["nextCursor"] is None


def test_findings_body_handles_summary_only_row() -> None:
    empty = {key: None for key in _row(1)} | {"hidden_anomalous": 4}
    body = findings_body(_query(), [empty], [], 50, None, 9, datetime(2026, 9, 27, tzinfo=timezone.utc), "d")
    assert body["items"] == [] and body["total"] == 0 and body["hiddenAnomalous"] == 4


def test_findings_unknown_institution_is_404() -> None:
    query = _query(mode="institution", institution="404")
    with pytest.raises(NotFound):
        findings_body(query, [], [{"legacy_id": 1, "short_name": None, "canonical_name": "Вуз"}], 50,
                      None, 9, datetime(2026, 9, 27, tzinfo=timezone.utc), "d")
