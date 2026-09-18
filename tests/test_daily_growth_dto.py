from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from api.dto import publication_list_item


def _row() -> dict[str, object]:
    row: dict[str, object] = {
        "publication_id": UUID("00000000-0000-4000-8000-000000000001"),
        "legacy_id": 1,
        "entity_type": "posts",
        "legacy_route": "/posts/1",
        "external_id": "1",
        "published_at": datetime(2026, 9, 18, tzinfo=timezone.utc),
        "public_url": "https://example.test/1",
        "publication_type": "text",
        "deleted_at": None,
        "history_completeness": "complete",
        "platform": "telegram",
        "is_repost": False,
        "quality_flags": {},
        "joint_authors": 0,
    }
    for metric in ("views", "reactions", "comments", "shares"):
        row[f"{metric}_count"] = 10
        row[f"{metric}_observed_at"] = datetime(2026, 9, 18, tzinfo=timezone.utc)
        row[f"{metric}_quality"] = "exact"
    return row


def test_publication_growth_is_absent_until_a_day_is_requested() -> None:
    assert publication_list_item(_row())["dailyGrowth"] is None


def test_publication_growth_keeps_nullable_metric_boundaries() -> None:
    row = _row() | {
        "growth_day": date(2026, 9, 18),
        "day_reactions_gain": 149,
        "day_views_gain": None,
    }
    assert publication_list_item(row)["dailyGrowth"] == {
        "day": "2026-09-18",
        "reactions": 149,
        "views": None,
    }
