from __future__ import annotations

from pathlib import Path
import sqlite3
from uuid import UUID

import pytest

from app.database import Database
from app.telegram_identity import (
    parse_telegram_external_id,
    telegram_message_external_id,
    telegram_publication_external_id,
)
from migration.bridge.cli import main as bridge_main
from migration.bridge.fixture import build_golden_fixture
from migration.bridge.mapping import mapping_as_rows, validate_mapping
from migration.bridge.model import BridgeOptions, stable_bigint, stable_uuid
from migration.bridge.normalize import as_utc, completeness, sanitize_evidence
from migration.bridge.source import LegacySource, create_online_backup
from migration.bridge.target import PostgresTarget
from migration.reverse_sync_format import (
    ReversePublicationEnvelope,
    ReverseSnapshotEnvelope,
    add_reverse_publication_envelope,
    parse_reverse_publication_envelope,
    parse_reverse_snapshot_envelope,
)


def source_database(path: Path) -> Path:
    database = Database(path)
    database.migrate()
    database.add_channel("bridge_example")
    return path


def test_stable_uuid_is_deterministic_and_namespace_scoped():
    first = stable_uuid("m-ranked-production", "institution", {"legacy_id": 7})
    assert isinstance(first, UUID)
    assert first == stable_uuid(
        "m-ranked-production", "institution", {"legacy_id": 7}
    )
    assert first != stable_uuid("another-source", "institution", {"legacy_id": 7})
    assert first != stable_uuid("m-ranked-production", "publication", {"legacy_id": 7})
    assert stable_bigint("m-ranked-production", "snapshot", 7) < 0
    assert stable_bigint("m-ranked-production", "snapshot", 7) == stable_bigint(
        "m-ranked-production", "snapshot", 7
    )


def test_telegram_target_identity_namespace_matches_logical_post_shape():
    assert telegram_publication_external_id(101) == "m:101"
    assert telegram_publication_external_id(101, 777) == "g:777"
    assert telegram_message_external_id(102) == "m:102"
    assert parse_telegram_external_id("m:102") == ("m", 102)
    assert parse_telegram_external_id("g:777") == ("g", 777)
    for ambiguous in ("102", "m:00102", "x:102", "m:-1", "m:0"):
        with pytest.raises(ValueError):
            parse_telegram_external_id(ambiguous)


def test_bridge_publication_audit_accepts_both_telegram_ambiguity_flag_names():
    captured: dict[str, str] = {}

    class CapturingTarget(PostgresTarget):
        def __init__(self) -> None:
            pass

        def _named_row(self, sql, names, params=()):
            captured["sql"] = sql
            return dict.fromkeys(names, 0)

    CapturingTarget().publication_summary(
        UUID("10000000-0000-4000-8000-000000000001"),
        UUID("20000000-0000-4000-8000-000000000001"),
        "posts",
    )

    assert "quality_flags->'ambiguous_album_reactions'" in captured["sql"]
    assert "quality_flags->'ambiguous_reactions'" in captured["sql"]


def test_reverse_snapshot_envelope_round_trips_target_identity():
    envelope = ReverseSnapshotEnvelope(
        legacy_table="reaction_snapshots",
        publication_id=UUID("30000000-0000-4000-8000-000000000001"),
        published_month=as_utc("2026-09-01T00:00:00Z").date(),
        snapshot_id=123,
        collected_at=as_utc("2026-09-03T09:00:01Z"),
        quality="exact",
        interval_uncertain=False,
        synthetic=False,
        metric_semantics_version=1,
        capability_version=1,
        source_fingerprint="target-fingerprint",
        created_at=as_utc("2026-09-03T09:00:02Z"),
    )

    assert parse_reverse_snapshot_envelope(envelope.as_json()) == envelope
    assert parse_reverse_snapshot_envelope('{"ordinary":"legacy raw"}') is None
    damaged = envelope.as_payload()
    damaged["_mranked_reverse_sync"]["version"] = 999
    with pytest.raises(ValueError, match="unsupported"):
        parse_reverse_snapshot_envelope(damaged)


def test_reverse_publication_envelope_preserves_legacy_object_and_is_strict():
    envelope = ReversePublicationEnvelope(
        legacy_table="platform_posts",
        publication_id=UUID("30000000-0000-4000-8000-000000000002"),
        quality_flags={"joint_post": True, "additional_author_count": 2},
        identities=({
            "external_id": "-1_2",
            "source_external_id": "-3_2",
            "role": "primary",
            "public_url": "https://vk.com/wall-3_2",
        },),
    )
    encoded = add_reverse_publication_envelope('{"legacy":"kept"}', envelope)

    assert '"legacy": "kept"' in encoded
    assert parse_reverse_publication_envelope(encoded) == envelope
    assert parse_reverse_publication_envelope('{"ordinary":true}') is None
    damaged = envelope.as_payload()
    damaged["_mranked_reverse_publication"]["identities"] = []
    with pytest.raises(ValueError, match="non-empty"):
        parse_reverse_publication_envelope(damaged)


def test_bridge_options_reject_unstable_or_unbounded_input(tmp_path):
    with pytest.raises(ValueError, match="source_namespace"):
        BridgeOptions(tmp_path / "source.db", "")
    with pytest.raises(ValueError, match="batch_size"):
        BridgeOptions(tmp_path / "source.db", "production", batch_size=0)


def test_online_backup_is_verified_read_only_and_does_not_modify_source(tmp_path):
    source_path = source_database(tmp_path / "source.db")
    before = source_path.read_bytes()
    destination = tmp_path / "S0.db"

    result = create_online_backup(source_path, destination)

    assert source_path.read_bytes() == before
    assert result["quick_check"] == "ok"
    assert result["foreign_key_violations"] == 0
    assert len(result["sha256"]) == 64
    assert destination.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(f"{destination.as_uri()}?mode=ro", uri=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM channels").fetchone()[0] == 1
    with pytest.raises(FileExistsError):
        create_online_backup(source_path, destination)


def test_online_backup_folds_a_committed_live_wal_into_standalone_file(tmp_path):
    source_path = tmp_path / "live.db"
    connection = sqlite3.connect(source_path)
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        connection.execute("CREATE TABLE event (id INTEGER PRIMARY KEY, value TEXT)")
        connection.commit()
        connection.execute("INSERT INTO event(value) VALUES ('committed-in-wal')")
        connection.commit()
        wal_path = source_path.with_name(f"{source_path.name}-wal")
        assert wal_path.stat().st_size > 0

        destination = tmp_path / "S-final.db"
        result = create_online_backup(source_path, destination)

        assert result["quick_check"] == "ok"
        destination_wal = destination.with_name(f"{destination.name}-wal")
        assert not destination_wal.exists() or destination_wal.stat().st_size == 0
        with sqlite3.connect(f"{destination.as_uri()}?mode=ro", uri=True) as backup:
            assert backup.execute("SELECT value FROM event").fetchone()[0] == "committed-in-wal"
    finally:
        connection.close()


def test_inventory_and_column_mapping_cover_current_schema(tmp_path):
    source_path = source_database(tmp_path / "source.db")
    source = LegacySource(source_path)

    inventory = source.inventory()

    assert inventory.quick_check == "ok"
    assert inventory.foreign_key_violations == 0
    assert inventory.schema_version == 15
    assert inventory.source_size_bytes > 0
    assert len(inventory.source_sha256) == 64
    assert {table.name for table in inventory.tables} >= {
        "institutions",
        "platform_accounts",
        "channels",
        "posts",
        "reaction_snapshots",
    }
    assert validate_mapping(source) == []
    statuses = {row["status"] for row in mapping_as_rows()}
    assert statuses <= {
        "mapped",
        "derived-and-verified",
        "preserved-as-evidence",
        "intentionally-deprecated-after-acceptance",
    }


def test_legacy_source_batches_resume_strictly_after_rowid(tmp_path):
    source_path = source_database(tmp_path / "source.db")
    database = Database(source_path)
    database.add_channel("bridge_second")
    source = LegacySource(source_path)

    batches = list(source.iter_rows("channels", batch_size=1))
    assert len(batches) == 2
    first_rowid = batches[0][0]["__source_rowid"]
    resumed = list(source.iter_rows("channels", after_rowid=first_rowid, batch_size=10))
    assert [row["username"] for row in resumed[0]] == ["bridge_second"]


def test_legacy_source_rejects_a_live_nonempty_wal(tmp_path):
    source_path = tmp_path / "live.db"
    connection = sqlite3.connect(source_path)
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        connection.execute("CREATE TABLE example (id INTEGER PRIMARY KEY)")
        connection.commit()
        connection.execute("INSERT INTO example DEFAULT VALUES")
        connection.commit()
        wal_path = source_path.with_name(f"{source_path.name}-wal")
        assert wal_path.stat().st_size > 0
        with pytest.raises(RuntimeError, match="consistent backup"):
            LegacySource(source_path)
    finally:
        connection.close()


def test_normalization_preserves_utc_completeness_and_redacts_secrets():
    assert as_utc("2026-09-03T12:00:00").isoformat() == "2026-09-03T12:00:00+00:00"
    assert completeness({"history_complete": 1, "history_forced_incomplete": 1}) == (
        "forced_incomplete"
    )
    assert sanitize_evidence(
        {"metrics": {"views": 0}, "access_token": "secret", "nested": [{"cookie": "x"}]}
    ) == {
        "metrics": {"views": 0},
        "access_token": "[REDACTED]",
        "nested": [{"cookie": "[REDACTED]"}],
    }


def test_import_dry_run_needs_no_postgres_and_writes_reports(tmp_path, capsys):
    source_path = source_database(tmp_path / "source.db")
    report_dir = tmp_path / "reports"

    result = bridge_main(
        [
            "import",
            str(source_path),
            "--source-namespace",
            "test-fixture",
            "--snapshot-kind",
            "fixture",
            "--dry-run",
            "--report-dir",
            str(report_dir),
            "--stem",
            "dry-run",
        ]
    )

    assert result == 0
    assert (report_dir / "dry-run.json").is_file()
    assert (report_dir / "dry-run.md").is_file()
    captured = capsys.readouterr().out
    assert '"status": "pass"' in captured
    assert "postgresql://" not in captured


def test_golden_fixture_is_canonically_deterministic_and_covers_edge_semantics(tmp_path):
    first_path = tmp_path / "first.db"
    second_path = tmp_path / "second.db"

    first = build_golden_fixture(first_path)
    second = build_golden_fixture(second_path)
    first_inventory = LegacySource(first_path).inventory()
    second_inventory = LegacySource(second_path).inventory()

    assert {
        table.name: table.canonical_hash for table in first_inventory.tables
    } == {
        table.name: table.canonical_hash for table in second_inventory.tables
    }
    assert first["totals"] == second["totals"]
    totals = first["totals"]
    assert totals["reaction_snapshots.reactions_zero"] == 1
    assert totals["reaction_snapshots.negative_reaction_transitions"] == 1
    assert totals["reaction_snapshots.synthetic"] == 1
    assert totals["platform_snapshots.reactions_null"] == 1
    assert totals["platform_snapshots.reactions_zero"] == 1
    assert totals["posts.albums"] == 1
    assert totals["platform_posts.joint_posts"] == 1
    assert totals["official_rating_observation.rows"] == 6
    assert validate_mapping(LegacySource(first_path)) == []

    catch_up = build_golden_fixture(tmp_path / "catch-up.db", revision=2)
    assert catch_up["tables"]["reaction_snapshots"] == 4
    assert catch_up["tables"]["platform_snapshots"] == 4
    assert catch_up["totals"]["reaction_snapshots.reactions"] == 37
