from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

from api.institution_profile import STUDENT_COUNTS, institution_profile
from api.dto import account
from test_account_archive_url import _row


def test_reviewed_sources_have_unique_stable_ids_and_explicit_provenance():
    rows = json.loads(STUDENT_COUNTS.read_text())
    assert len(rows) == len({row["institutionId"] for row in rows}) == 84
    for row in rows:
        uuid.UUID(row["institutionId"])
        assert type(row["value"]) is int and row["value"] >= 0
        assert row["scope"] and row["sourceName"]
        assert re.fullmatch(r"[a-f0-9]{64}", row["sourceSha256"])
        url = urlsplit(row["sourceUrl"])
        assert url.scheme == "https"
        assert url.hostname and not url.username and not url.password
        assert not re.search(r"(?i)(token|signature|credential|expires)=", url.query)
        assert row["approximate"] is (url.hostname == "bru.by")
        assert row["referenceYear"] is None or 2024 <= row["referenceYear"] <= 2026
        assert datetime.fromisoformat(row["verifiedAt"]).date().isoformat() == row["verifiedAt"]
        if row.get("sourceBreakdown"):
            assert all(type(value) is int and value >= 0 for value in row["sourceBreakdown"].values())
            assert sum(row["sourceBreakdown"].values()) == row["value"]
        for source in row.get("sourceDocuments", []):
            assert re.fullmatch(r"[a-f0-9]{64}", source["sha256"])
            assert urlsplit(source["url"]).scheme == "https"
        if row.get("referenceDate"):
            assert datetime.fromisoformat(row["referenceDate"]).year == row["referenceYear"]


def test_account_and_siblings_share_institution_enrollment_not_platform_date():
    mipt = next(row for row in json.loads(STUDENT_COUNTS.read_text())
                if urlsplit(row["sourceUrl"]).hostname == "mipt.ru")
    started = datetime(2026, 8, 29, 17, 31, tzinfo=timezone.utc)
    for platform in ("telegram", "vk", "max", "rutube"):
        row = _row(platform, None)
        row.update(institution_id=mipt["institutionId"], institution_tracking_started_at=started,
                   created_at=datetime(2026, 9, 21, tzinfo=timezone.utc))
        profile = account(row, 17)["institutionProfile"]
        assert profile["trackingStartedAt"] == started.isoformat()
        assert profile["students"]["value"] == 8202
        assert profile["students"]["referenceYear"] == 2026
        assert profile["students"]["referenceDate"] == "2026-09-30"
        assert "sourceSha256" not in profile["students"]


def test_unknown_institution_has_no_invented_date_or_count():
    assert institution_profile({"institution_id": uuid.uuid4()}) == {
        "trackingStartedAt": None, "students": None,
    }


def test_swsu_current_statement_excludes_postgraduate_and_vocational_students():
    source = next(row for row in json.loads(STUDENT_COUNTS.read_text())
                  if row["institutionId"] == "4239057a-57e6-550f-b86a-32c590b25dc1")
    assert source["value"] == sum(source["sourceBreakdown"].values()) == 8560
    assert source["value"] + sum(source["sourceExcluded"].values()) == source["sourceDocumentTotal"] == 9174
    students = institution_profile({"institution_id": source["institutionId"]})["students"]
    assert students["referenceDate"] == "2026-07-08"
    assert students["referenceYear"] == 2026
    assert students["value"] == 8560


def test_a_response_cannot_mutate_the_cached_source():
    institution_id = json.loads(STUDENT_COUNTS.read_text())[0]["institutionId"]
    row = {"institution_id": institution_id}
    profile = institution_profile(row)
    expected = profile["students"]["value"]
    profile["students"]["value"] = 0
    assert institution_profile(row)["students"]["value"] == expected


def test_undated_source_does_not_inherit_the_verification_year():
    source = next(row for row in json.loads(STUDENT_COUNTS.read_text())
                  if row["institutionId"] == "e15cab1d-8815-50fa-baa8-96f6edd1bc4f")
    students = institution_profile({"institution_id": source["institutionId"]})["students"]
    assert students["value"] == 37861
    assert students["referenceYear"] is None
    assert students["referenceDate"] is None
    assert students["verifiedAt"] == "2026-10-03"
