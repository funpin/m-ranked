from __future__ import annotations

from datetime import date, datetime, timezone
import json
from typing import Any
from uuid import UUID

from collector_target.legacy_csv import persist_native_csv_batch


NOW = datetime(2026, 9, 17, 1, 0, tzinfo=timezone.utc)


class _Cursor:
    def __init__(self, connection: "_Connection") -> None:
        self.connection = connection
        self.rows: list[dict[str, Any]] = []

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, sql: str, params: Any) -> None:
        normalized = " ".join(sql.split())
        if "publication_metric_snapshot_resolved" in normalized:
            self.rows = self.connection.snapshots
        elif "FROM ingest.publication_identity" in normalized:
            self.rows = self.connection.identities
        elif "FROM ingest.reaction_breakdown" in normalized:
            self.rows = self.connection.reactions
        else:  # pragma: no cover - guard for an unexpected query
            raise AssertionError(normalized)

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _Connection:
    def __init__(self) -> None:
        telegram_id = UUID("30000000-0000-4000-8000-000000000001")
        vk_id = UUID("30000000-0000-4000-8000-000000000002")
        common = {
            "published_month": date(2026, 9, 1),
            "published_at": NOW,
            "publication_type": "text",
            "collected_at": NOW,
            "quality": "exact",
            "interval_uncertain": False,
            "synthetic": False,
            "metric_semantics_version": 1,
            "capability_version": 1,
            "source_fingerprint": "a" * 64,
            "created_at": NOW,
            "views_quality": "exact",
            "reactions_quality": "exact",
            "comments_quality": "exact",
            "shares_quality": "unknown",
            "metric_evidence": {"views": {"quality": "exact"}},
            "observed_at": NOW,
            "age_seconds": 3600,
        }
        self.snapshots = [
            {**common, "id": 10, "publication_id": telegram_id, "platform": "telegram"},
            {**common, "id": 11, "publication_id": vk_id, "platform": "vk"},
        ]
        self.identities = [
            {
                "publication_id": telegram_id,
                "external_id": "m:42",
                "role": "primary",
                "public_url": "https://t.me/example/42",
            },
            {
                "publication_id": vk_id,
                "external_id": "wall-1_2",
                "role": "primary",
                "public_url": "https://vk.com/wall-1_2",
            },
        ]
        self.reactions = [
            {
                "snapshot_published_month": date(2026, 9, 1),
                "snapshot_id": 10,
                "reaction_key": "like",
                "reaction_count": 3,
            },
        ]
        self.calls: list[tuple[str, Any]] = []

    def cursor(self, **_kwargs: Any) -> _Cursor:
        return _Cursor(self)

    def execute(self, sql: str, params: Any) -> None:
        self.calls.append((" ".join(sql.split()), params))


def test_native_csv_batch_serializes_multiple_platforms_in_one_insert() -> None:
    connection = _Connection()
    observations = [
        (
            connection.snapshots[0]["publication_id"],
            date(2026, 9, 1),
            10,
            {"source": "telegram"},
        ),
        (
            connection.snapshots[1]["publication_id"],
            date(2026, 9, 1),
            11,
            {"source": "vk"},
        ),
    ]

    persist_native_csv_batch(connection, observations)

    assert len(connection.calls) == 2
    alias_ids = connection.calls[0][1][0]
    assert alias_ids == [item[0] for item in observations]
    lexemes = json.loads(connection.calls[1][1][0])
    assert len(lexemes) == 2
    assert lexemes[0]["public_fields"]["telegram_message_id"] == 42
    assert "telegram_message_id" not in lexemes[1]["public_fields"]
    telegram_fields = lexemes[0]["fields"]
    assert json.loads(telegram_fields["reactions_json"]) == {"like": 3}
    assert json.loads(telegram_fields["raw_json"])["_source_payload"] == {
        "source": "telegram",
    }
