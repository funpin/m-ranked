from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from typing import Any, Mapping
from uuid import UUID

from migration.bridge.fixture import build_golden_fixture
from migration.bridge.source import LegacySource, create_online_backup
from operations.reverse_sync.journal import ReverseSyncJournal
from operations.reverse_sync.model import SyncPlan
from operations.reverse_sync.service import ReverseSyncService
from operations.reverse_sync.sqlite_target import LegacySqliteTarget


UTC = timezone.utc
SOURCE_NAMESPACE = "pytest/reverse-snapshot-alias"
GENERATED_AT = datetime(2026, 9, 4, 12, tzinfo=UTC)
TELEGRAM_PUBLICATION_ID = UUID("11111111-1111-4111-8111-111111111111")
PLATFORM_PUBLICATION_ID = UUID("22222222-2222-4222-8222-222222222222")


def _snapshot(
    *,
    target_id: int,
    publication_id: UUID,
    platform: str,
    sampling_bucket: int,
    published_month: str = "2026-09-01",
) -> dict[str, Any]:
    observed_at = GENERATED_AT + timedelta(seconds=sampling_bucket)
    telegram = platform == "telegram"
    return {
        "published_month": published_month,
        "id": target_id,
        "publication_id": publication_id,
        "platform": platform,
        "observed_at": observed_at,
        "collected_at": observed_at + timedelta(seconds=1),
        "sampling_bucket": sampling_bucket,
        "age_seconds": sampling_bucket,
        "views_count": 100 + target_id,
        "reactions_count": 2,
        "comments_count": 0,
        "shares_count": None if telegram else 1,
        "reaction_breakdown": {"like": 2} if telegram else {},
        "quality": "exact",
        "interval_uncertain": False,
        "synthetic": False,
        "metric_semantics_version": 1,
        "capability_version": 1,
        "source_fingerprint": f"snapshot-{platform}-{target_id}",
        "created_at": observed_at + timedelta(seconds=2),
    }


def _plan(*snapshots: Mapping[str, Any]) -> SyncPlan:
    return SyncPlan(
        baseline_revision_ids=(1,),
        revision_ids=(2,),
        revisions=(),
        accounts=(),
        publications=(),
        snapshots=tuple(snapshots),
        collection_runs=(),
        generated_at=GENERATED_AT,
    )


def _service(
    target: LegacySqliteTarget,
    journal: ReverseSyncJournal,
) -> ReverseSyncService:
    source = SimpleNamespace(source_namespace=SOURCE_NAMESPACE)
    return ReverseSyncService(source, target, journal)  # type: ignore[arg-type]


def _prepare_target(tmp_path: Path) -> tuple[LegacySqliteTarget, dict[str, int]]:
    path = tmp_path / "legacy.sqlite"
    build_golden_fixture(path, revision=1)
    # Make the two per-table high-water marks deliberately different. Snapshot
    # rows have no children, so changing these fixture-only primary keys is safe.
    with sqlite3.connect(path) as connection:
        connection.execute(
            """UPDATE reaction_snapshots SET id=700
                 WHERE id=(SELECT max(id) FROM reaction_snapshots)"""
        )
        connection.execute(
            """UPDATE platform_snapshots SET id=900
                 WHERE id=(SELECT max(id) FROM platform_snapshots)"""
        )
    target = LegacySqliteTarget(path, SOURCE_NAMESPACE, min_free_bytes=0)
    return target, target.maximum_legacy_ids()


def test_snapshot_aliases_are_positive_table_scoped_and_stable_after_restart(
    tmp_path: Path,
) -> None:
    target, maximums = _prepare_target(tmp_path)
    journal = ReverseSyncJournal(tmp_path / "reverse-sync-journal.sqlite")
    journal.initialize()
    first_service = _service(target, journal)
    telegram_first = _snapshot(
        target_id=10_001,
        publication_id=TELEGRAM_PUBLICATION_ID,
        platform="telegram",
        sampling_bucket=91_001,
    )
    telegram_second = _snapshot(
        target_id=10_002,
        publication_id=TELEGRAM_PUBLICATION_ID,
        platform="telegram",
        sampling_bucket=91_002,
    )
    platform_first = _snapshot(
        target_id=10_001,
        publication_id=PLATFORM_PUBLICATION_ID,
        platform="vk",
        sampling_bucket=92_001,
    )
    platform_second = _snapshot(
        target_id=10_002,
        publication_id=PLATFORM_PUBLICATION_ID,
        platform="vk",
        sampling_bucket=92_002,
    )

    # Simulate a crash after only part of the reservation set was committed.
    partial = first_service._reserve_snapshot_aliases(
        _plan(telegram_first, platform_first), maximums
    )
    partial_ids = {
        str(snapshot["platform"]): int(snapshot["legacy_id"])
        for snapshot in partial.snapshots
    }
    assert partial_ids == {
        "telegram": maximums["reaction_snapshots"] + 1,
        "vk": maximums["platform_snapshots"] + 1,
    }

    restarted = _service(
        target,
        ReverseSyncJournal(journal.path),
    )
    unreserved = _plan(
        telegram_first,
        telegram_second,
        platform_first,
        platform_second,
    )
    reserved = restarted._reserve_snapshot_aliases(unreserved, maximums)
    by_platform = {
        str(snapshot["platform"]): [
            int(item["legacy_id"])
            for item in reserved.snapshots
            if item["platform"] == snapshot["platform"]
        ]
        for snapshot in reserved.snapshots
    }
    assert by_platform == {
        "telegram": [
            maximums["reaction_snapshots"] + 1,
            maximums["reaction_snapshots"] + 2,
        ],
        "vk": [
            maximums["platform_snapshots"] + 1,
            maximums["platform_snapshots"] + 2,
        ],
    }
    assert all(
        legacy_id > 0 for legacy_ids in by_platform.values() for legacy_id in legacy_ids
    )

    replay = restarted._reserve_snapshot_aliases(unreserved, maximums)
    fixed = restarted._attach_snapshot_aliases(unreserved)
    assert replay.snapshots == reserved.snapshots
    assert replay.digest == reserved.digest == fixed.digest
    assert unreserved.digest != reserved.digest
    changed_first = {**reserved.snapshots[0], "legacy_id": 999_999}
    assert replace(
        reserved,
        snapshots=(changed_first, *reserved.snapshots[1:]),
    ).digest != reserved.digest


def test_reserved_snapshot_ids_replay_and_cross_forward_rowid_checkpoints(
    tmp_path: Path,
) -> None:
    target, maximums = _prepare_target(tmp_path)
    with sqlite3.connect(target.path) as connection:
        telegram_post_id = int(
            connection.execute("SELECT min(id) FROM posts").fetchone()[0]
        )
        platform_post_id = int(
            connection.execute("SELECT min(id) FROM platform_posts").fetchone()[0]
        )
    journal = ReverseSyncJournal(tmp_path / "reverse-sync-journal.sqlite")
    journal.initialize()
    service = _service(target, journal)
    unreserved = _plan(
        _snapshot(
            target_id=20_001,
            publication_id=TELEGRAM_PUBLICATION_ID,
            platform="telegram",
            sampling_bucket=93_001,
        ),
        _snapshot(
            target_id=20_001,
            publication_id=PLATFORM_PUBLICATION_ID,
            platform="vk",
            sampling_bucket=94_001,
        ),
    )
    reserved = service._reserve_snapshot_aliases(unreserved, maximums)
    aliases = {
        TELEGRAM_PUBLICATION_ID: ("posts", telegram_post_id),
        PLATFORM_PUBLICATION_ID: ("platform_posts", platform_post_id),
    }

    target.apply(reserved, aliases)
    # This is the crash window after the legacy commit and before the applied
    # checkpoint: a replay must use the same IDs and remain idempotent.
    replay = _service(target, ReverseSyncJournal(journal.path))._reserve_snapshot_aliases(
        unreserved,
        target.maximum_legacy_ids(),
    )
    assert replay.digest == reserved.digest
    target.apply(replay, aliases)

    expected = {
        "reaction_snapshots": int(reserved.snapshots[0]["legacy_id"]),
        "platform_snapshots": int(reserved.snapshots[1]["legacy_id"]),
    }
    assert expected == {
        "reaction_snapshots": maximums["reaction_snapshots"] + 1,
        "platform_snapshots": maximums["platform_snapshots"] + 1,
    }

    target.durability_barrier()
    export = tmp_path / "legacy-forward-source.sqlite"
    create_online_backup(target.path, export)
    source = LegacySource(export)
    for table, legacy_id in expected.items():
        batches = tuple(
            source.iter_rows(
                table,
                after_rowid=maximums[table],
                batch_size=1,
            )
        )
        rows = [row for batch in batches for row in batch]
        assert [int(row["__source_rowid"]) for row in rows] == [legacy_id]
        assert [int(row["id"]) for row in rows] == [legacy_id]
