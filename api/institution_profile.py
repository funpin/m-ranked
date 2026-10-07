"""Reviewed public student counts; never fetch external sources on a page read."""
from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

STUDENT_COUNTS = Path(__file__).with_name("data") / "institution-student-counts.json"
PUBLIC_FIELDS = ("value", "referenceYear", "referenceDate", "approximate", "sourceUrl", "sourceLabel", "scope", "verifiedAt")


@functools.cache
def _students_by_institution() -> dict[str, dict[str, Any]]:
    rows = json.loads(STUDENT_COUNTS.read_text(encoding="utf-8"))
    return {row["institutionId"]: {key: row[key] for key in PUBLIC_FIELDS if key in row} for row in rows}


def institution_profile(row: dict[str, Any]) -> dict[str, Any]:
    # Earliest recorded catalogue enrollment, including pre-migration accounts.
    # Deleted accounts retain their original date; polling/retention do not reset it.
    added = row.get("institution_tracking_started_at")
    students = _students_by_institution().get(str(row["institution_id"]))
    return {
        "trackingStartedAt": added.isoformat() if hasattr(added, "isoformat") else added,
        "students": dict(students) if students is not None else None,
    }
