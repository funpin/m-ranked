from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import stat
from typing import Any, Iterator, Mapping, Sequence
from uuid import UUID, uuid4

import pytest

from operations.reverse_sync import cli
from operations.reverse_sync.journal import ReverseSyncJournal
from operations.reverse_sync.model import (
    JournalState,
    Revision,
    STATE_VERSION,
    SyncPlan,
    canonical_json,
    payload_sha256,
    require_nonempty,
    require_revision_ids,
)
from operations.reverse_sync.service import ReverseSyncService
from operations.reverse_sync.sqlite_target import LegacySqliteTarget


UTC = timezone.utc
FIXED_NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)


def _state(**changes: Any) -> JournalState:
    values: dict[str, Any] = {
        "status": "active",
        "source_namespace": "fixture/source",
        "operator": "migration-operator",
        "ticket": "CHG-42",
        "started_at": FIXED_NOW,
        "rollback_deadline": FIXED_NOW + timedelta(hours=24),
        "s_final_batch_id": UUID("f34650c5-4161-44d6-9e5a-09d7f25c0874"),
        "s_final_source_sha256": "b" * 64,
    }
    values.update(changes)
    return JournalState(**values)


def _revision(revision_id: int) -> Revision:
    return Revision(
        id=revision_id,
        cause="ingestion",
        source_run_id=UUID(int=revision_id),
        committed_at=FIXED_NOW + timedelta(minutes=revision_id),
        correlation_id=UUID(int=100 + revision_id),
        metadata={"revision": revision_id},
    )


def test_model_canonicalization_is_stable_and_rejects_naive_datetimes():
    value = {
        "uuid": UUID("61cfa09d-a49c-4bd5-a39b-04dc4b141ad6"),
        "timestamp": datetime(2026, 9, 4, 15, tzinfo=timezone(timedelta(hours=3))),
        "decimal": Decimal("1.250"),
        "integral": Decimal("2.0"),
        "bytes": b"\x00\xff",
        "nested": {"z": 1, "a": 2},
    }

    encoded = canonical_json(value)

    assert encoded == canonical_json(dict(reversed(tuple(value.items()))))
    assert json.loads(encoded) == {
        "bytes": "00ff",
        "decimal": "1.250",
        "integral": 2,
        "nested": {"a": 2, "z": 1},
        "timestamp": "2026-09-04T12:00:00+00:00",
        "uuid": "61cfa09d-a49c-4bd5-a39b-04dc4b141ad6",
    }
    assert len(payload_sha256(value)) == 64
    with pytest.raises(ValueError, match="timezone-aware"):
        canonical_json({"timestamp": datetime(2026, 9, 4, 12)})


def test_model_validates_operator_fields_and_revision_sets():
    assert require_nonempty("  CHG-42  ", "ticket") == "CHG-42"
    assert require_revision_ids([9, 2, 9, 4]) == (2, 4, 9)
    with pytest.raises(ValueError, match="must not be blank"):
        require_nonempty("  ", "operator")
    with pytest.raises(ValueError, match="control character"):
        require_nonempty("operator\nforged", "operator")
    with pytest.raises(ValueError, match="positive"):
        require_revision_ids([1, 0])


def test_sync_plan_digest_excludes_generation_time_but_covers_payload():
    first = SyncPlan(
        baseline_revision_ids=(1,),
        revision_ids=(2,),
        revisions=(_revision(2),),
        accounts=({"id": "account", "title": "Original"},),
        publications=(),
        snapshots=(),
        collection_runs=(),
        generated_at=FIXED_NOW,
    )

    assert replace(first, generated_at=FIXED_NOW + timedelta(hours=1)).digest == first.digest
    assert replace(
        first,
        accounts=({"id": "account", "title": "Changed"},),
    ).digest != first.digest


def test_journal_roundtrip_permissions_checkpoints_and_alias_immutability(
    tmp_path: Path,
):
    journal = ReverseSyncJournal(tmp_path / "state" / "reverse-sync.sqlite")
    journal.initialize()

    assert stat.S_IMODE(journal.path.stat().st_mode) == 0o600
    assert journal.integrity() == {
        "exists": True,
        "quickCheck": "ok",
        "schemaVersion": STATE_VERSION,
    }

    state = _state()
    journal.save_state(state, "started")
    assert journal.load_state() == state

    target_identity = "d" * 64
    journal.bind_legacy_target(target_identity)
    journal.bind_legacy_target(target_identity)
    assert journal.legacy_target_identity() == target_identity
    with pytest.raises(RuntimeError, match="target binding changed"):
        journal.bind_legacy_target("e" * 64)

    journal.replace_revisions("baseline_revision", (9, 2, 4))
    assert journal.revision_ids("baseline_revision") == (2, 4, 9)
    with pytest.raises(ValueError, match="invalid revision journal table"):
        journal.revision_ids("journal_event; DROP TABLE sync_state")

    target_id = uuid4()
    journal.record_alias("posts", target_id, 101)
    journal.record_alias("posts", target_id, 101)
    with pytest.raises(RuntimeError, match="changed identity"):
        journal.record_alias("posts", target_id, 102)

    digest = "a" * 64
    journal.record_applied((9, 2), digest)
    checkpoint = journal.applied_checkpoint()
    assert checkpoint["revisionIds"] == (2, 9)
    assert checkpoint["planDigest"] == digest
    assert datetime.fromisoformat(checkpoint["appliedAt"]).tzinfo is not None
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        journal.record_applied((2,), "A" * 64)


def test_journal_refuses_a_symlink_path(tmp_path: Path):
    real_path = tmp_path / "real.sqlite"
    real_path.touch()
    link_path = tmp_path / "journal.sqlite"
    link_path.symlink_to(real_path)

    with pytest.raises(ValueError, match="must not be a symlink"):
        ReverseSyncJournal(link_path).initialize()


def test_journal_refuses_a_symlinked_rollback_sidecar(tmp_path: Path):
    journal = ReverseSyncJournal(tmp_path / "journal.sqlite")
    journal.initialize()
    decoy = tmp_path / "decoy"
    decoy.touch()
    Path(f"{journal.path}-journal").symlink_to(decoy)

    with pytest.raises(ValueError, match="must not be a symlink"):
        journal.integrity()


def test_journal_refuses_a_symlinked_ancestor(tmp_path: Path):
    real_directory = tmp_path / "real"
    real_directory.mkdir()
    linked_directory = tmp_path / "linked"
    linked_directory.symlink_to(real_directory, target_is_directory=True)

    with pytest.raises(ValueError, match="must not traverse symlinks"):
        ReverseSyncJournal(linked_directory / "journal.sqlite").initialize()


def test_journal_integrity_rejects_wrong_schema_version(tmp_path: Path):
    journal = ReverseSyncJournal(tmp_path / "journal.sqlite")
    journal.initialize()
    with sqlite3.connect(journal.path) as connection:
        connection.execute(
            "UPDATE journal_meta SET value='999' WHERE key='schema_version'"
        )

    with pytest.raises(RuntimeError, match="schema version is unsupported"):
        journal.integrity()


def test_journal_integrity_rejects_an_unexpected_table(tmp_path: Path):
    journal = ReverseSyncJournal(tmp_path / "journal.sqlite")
    journal.initialize()
    with sqlite3.connect(journal.path) as connection:
        connection.execute("CREATE TABLE injected_table(value TEXT)")

    with pytest.raises(RuntimeError, match="table set is invalid"):
        journal.integrity()


def test_journal_integrity_rejects_an_unexpected_column(tmp_path: Path):
    journal = ReverseSyncJournal(tmp_path / "journal.sqlite")
    journal.initialize()
    with sqlite3.connect(journal.path) as connection:
        connection.execute("ALTER TABLE journal_event ADD COLUMN injected TEXT")

    with pytest.raises(RuntimeError, match="table layout is invalid"):
        journal.integrity()


def test_journal_integrity_rejects_group_readable_permissions(tmp_path: Path):
    journal = ReverseSyncJournal(tmp_path / "journal.sqlite")
    journal.initialize()
    journal.path.chmod(0o640)

    with pytest.raises(PermissionError, match="permissions are too broad"):
        journal.integrity()


def test_journal_load_rejects_incoherent_persisted_timestamps(tmp_path: Path):
    journal = ReverseSyncJournal(tmp_path / "journal.sqlite")
    journal.initialize()
    journal.save_state(_state(), "started")
    payload = _state().as_dict()
    payload["status"] = "verified"
    payload["planDigest"] = "a" * 64
    with sqlite3.connect(journal.path) as connection:
        connection.execute(
            "UPDATE sync_state SET payload=? WHERE singleton=1",
            (canonical_json(payload),),
        )

    with pytest.raises(RuntimeError, match="timestamps are incoherent"):
        journal.load_state()


def test_journal_save_rejects_out_of_order_timestamps(tmp_path: Path):
    journal = ReverseSyncJournal(tmp_path / "journal.sqlite")
    journal.initialize()
    invalid = _state(
        status="stopped",
        plan_digest="a" * 64,
        drained_at=FIXED_NOW + timedelta(hours=3),
        verified_at=FIXED_NOW + timedelta(hours=2),
        stopped_at=FIXED_NOW + timedelta(hours=4),
    )

    with pytest.raises(RuntimeError, match="timestamps are out of order"):
        journal.save_state(invalid, "stopped")


def test_legacy_target_identity_is_stable_for_projected_rows_but_binds_baseline(
    tmp_path: Path,
):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT);
            CREATE TABLE institutions(
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                short_name TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE projected_rows(id INTEGER PRIMARY KEY, value TEXT);
            INSERT INTO schema_migrations(version,applied_at)
            VALUES(15,'2026-09-04T00:00:00+00:00');
            INSERT INTO institutions(id,name,short_name,created_at)
            VALUES(1,'Institution','INST','2026-09-04T00:00:00+00:00');
            """
        )
    target = LegacySqliteTarget(path, "fixture/source", min_free_bytes=0)
    baseline_identity = target.identity()

    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO projected_rows(id,value) VALUES(1,'compatibility update')"
        )
    assert target.identity() == baseline_identity

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE institutions SET name='Different institution' WHERE id=1"
        )
    assert target.identity() != baseline_identity


def test_legacy_target_refuses_a_symlinked_rollback_sidecar(tmp_path: Path):
    target = LegacySqliteTarget(
        tmp_path / "legacy.sqlite",
        "fixture/source",
        min_free_bytes=0,
    )
    decoy = tmp_path / "decoy"
    decoy.touch()
    Path(f"{target.path}-journal").symlink_to(decoy)

    with pytest.raises(ValueError, match="must not be symlinks"):
        target.identity()


def test_legacy_target_refuses_a_symlinked_ancestor(tmp_path: Path):
    real_directory = tmp_path / "real"
    real_directory.mkdir()
    linked_directory = tmp_path / "linked"
    linked_directory.symlink_to(real_directory, target_is_directory=True)
    target = LegacySqliteTarget(
        linked_directory / "legacy.sqlite",
        "fixture/source",
        min_free_bytes=0,
    )

    with pytest.raises(ValueError, match="must not traverse symlinks"):
        target.identity()


class _FakeService:
    def __init__(self, result: Mapping[str, Any] | None = None, error: BaseException | None = None):
        self.result = dict(result or {"status": "pass"})
        self.error = error

    def preflight(self) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        return dict(self.result)


def test_cli_writes_private_report_without_echoing_postgres_dsn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    postgres_dsn = "postgresql://migration@db.invalid/mranked"
    report = tmp_path / "reports" / "preflight.json"
    monkeypatch.setattr(cli, "_service", lambda _arguments: _FakeService())

    result = cli.main([
        "--postgres-dsn", postgres_dsn,
        "--legacy-sqlite", str(tmp_path / "legacy.sqlite"),
        "--journal-path", str(tmp_path / "journal.sqlite"),
        "--source-namespace", "fixture/source",
        "--report-path", str(report),
        "preflight",
    ])

    captured = capsys.readouterr()
    assert result == 0
    assert json.loads(captured.out) == {"command": "preflight", "status": "pass"}
    assert captured.err == ""
    assert postgres_dsn not in captured.out
    assert postgres_dsn not in report.read_text(encoding="utf-8")
    assert json.loads(report.read_text(encoding="utf-8")) == {
        "command": "preflight",
        "status": "pass",
    }
    assert stat.S_IMODE(report.stat().st_mode) == 0o600


def test_cli_publishes_running_report_before_service_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    report = tmp_path / "preflight.json"
    observed: list[dict[str, Any]] = []

    class InspectingService:
        def preflight(self) -> dict[str, str]:
            observed.append(json.loads(report.read_text(encoding="utf-8")))
            return {"status": "pass"}

    monkeypatch.setattr(cli, "_service", lambda _arguments: InspectingService())

    result = cli.main([
        "--postgres-dsn", "postgresql://redacted.invalid/mranked",
        "--legacy-sqlite", str(tmp_path / "legacy.sqlite"),
        "--journal-path", str(tmp_path / "journal.sqlite"),
        "--source-namespace", "fixture/source",
        "--report-path", str(report),
        "preflight",
    ])

    assert result == 0
    assert observed == [{"command": "preflight", "status": "running"}]
    assert json.loads(report.read_text(encoding="utf-8")) == {
        "command": "preflight",
        "status": "pass",
    }
    capsys.readouterr()


def test_cli_redacts_exception_text_that_may_contain_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    secret = "postgresql://migration:must-not-leak@db.invalid/mranked"
    monkeypatch.setattr(
        cli,
        "_service",
        lambda _arguments: _FakeService(error=RuntimeError(f"connection failed: {secret}")),
    )

    result = cli.main(["preflight"])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "command": "preflight",
        "errorCode": "RuntimeError",
        "status": "failed",
    }
    assert secret not in captured.err


@pytest.mark.parametrize(
    ("environment_name", "secret_value"),
    [
        ("REVERSE_SYNC_MIN_FREE_BYTES", "invalid-secret-size"),
        ("REVERSE_SYNC_POLL_SECONDS", "invalid-secret-interval"),
    ],
)
def test_cli_redacts_invalid_numeric_environment_defaults(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    environment_name: str,
    secret_value: str,
):
    monkeypatch.delenv("REVERSE_SYNC_MIN_FREE_BYTES", raising=False)
    monkeypatch.delenv("REVERSE_SYNC_POLL_SECONDS", raising=False)
    monkeypatch.setenv(environment_name, secret_value)

    result = cli.main(["preflight"])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "command": None,
        "errorCode": "ValueError",
        "status": "failed",
    }
    assert secret_value not in captured.err


def test_cli_redacts_invalid_typed_argv(
    capsys: pytest.CaptureFixture[str],
):
    secret_value = "invalid-secret-size"

    result = cli.main(["--min-free-bytes", secret_value, "preflight"])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "command": None,
        "errorCode": "ValueError",
        "status": "failed",
    }
    assert secret_value not in captured.err


def test_cli_rejects_password_bearing_dsn_from_argv_without_leaking_it(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    secret_dsn = "postgresql://migration:argv-secret@db.invalid/mranked"

    result = cli.main([
        "--postgres-dsn", secret_dsn,
        "--legacy-sqlite", str(tmp_path / "legacy.sqlite"),
        "--journal-path", str(tmp_path / "journal.sqlite"),
        "--source-namespace", "fixture/source",
        "preflight",
    ])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "command": "preflight",
        "errorCode": "ValueError",
        "status": "failed",
    }
    assert secret_dsn not in captured.err


def test_cli_accepts_password_bearing_dsn_from_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    secret_dsn = "postgresql://migration:environment-secret@db.invalid/mranked"
    monkeypatch.setenv("REVERSE_SYNC_DATABASE_URL", secret_dsn)
    arguments = cli.build_parser().parse_args([
        "--legacy-sqlite", str(tmp_path / "legacy.sqlite"),
        "--journal-path", str(tmp_path / "journal.sqlite"),
        "--source-namespace", "fixture/source",
        "preflight",
    ])

    service = cli._service(arguments)

    assert service.source._dsn == secret_dsn


@pytest.mark.parametrize(
    ("command", "service_result"),
    [
        ("once", {"status": "active", "caughtUp": False}),
        ("status", {"status": "active", "lagRevisionCount": 1}),
        (
            "status",
            {
                "status": "drained",
                "lagRevisionCount": 0,
                "unchangedSinceDrain": False,
            },
        ),
    ],
)
def test_cli_returns_temporary_failure_for_reverse_sync_lag(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    service_result: dict[str, Any],
):
    class LaggingService:
        def once(self) -> dict[str, Any]:
            return dict(service_result)

        def status(self) -> dict[str, Any]:
            return dict(service_result)

    monkeypatch.setattr(cli, "_service", lambda _arguments: LaggingService())

    result = cli.main([command])

    captured = capsys.readouterr()
    assert result == 75
    assert captured.err == ""
    assert json.loads(captured.out) == {"command": command, **service_result}


def test_cli_replaces_a_stale_pass_report_with_redacted_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    secret = "postgresql://migration:must-not-leak@db.invalid/mranked"
    report = tmp_path / "preflight.json"
    report.write_text('{"status":"pass"}\n', encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "_service",
        lambda _arguments: _FakeService(error=RuntimeError(f"failed: {secret}")),
    )

    result = cli.main([
        "--postgres-dsn", secret,
        "--legacy-sqlite", str(tmp_path / "legacy.sqlite"),
        "--journal-path", str(tmp_path / "journal.sqlite"),
        "--source-namespace", "fixture/source",
        "--report-path", str(report),
        "preflight",
    ])

    captured = capsys.readouterr()
    expected = {
        "command": "preflight",
        "errorCode": "RuntimeError",
        "status": "failed",
    }
    assert result == 1
    assert json.loads(captured.err) == expected
    assert json.loads(report.read_text(encoding="utf-8")) == expected
    assert secret not in captured.err
    assert secret not in report.read_text(encoding="utf-8")


def test_cli_reports_interrupt_and_returns_shell_interrupt_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    report = tmp_path / "preflight.json"
    report.write_text('{"status":"pass"}\n', encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "_service",
        lambda _arguments: _FakeService(error=KeyboardInterrupt()),
    )

    result = cli.main([
        "--postgres-dsn", "postgresql://redacted.invalid/mranked",
        "--legacy-sqlite", str(tmp_path / "legacy.sqlite"),
        "--journal-path", str(tmp_path / "journal.sqlite"),
        "--source-namespace", "fixture/source",
        "--report-path", str(report),
        "preflight",
    ])

    captured = capsys.readouterr()
    expected = {"command": "preflight", "status": "interrupted"}
    assert result == 130
    assert captured.out == ""
    assert json.loads(captured.err) == expected
    assert json.loads(report.read_text(encoding="utf-8")) == expected


@pytest.mark.parametrize("collision", ["legacy", "journal"])
def test_cli_rejects_a_report_that_would_replace_a_database(
    tmp_path: Path,
    collision: str,
):
    legacy = tmp_path / "legacy.sqlite"
    journal = tmp_path / "journal.sqlite"
    report = legacy if collision == "legacy" else journal
    arguments = cli.build_parser().parse_args([
        "--postgres-dsn", "postgresql://redacted.invalid/mranked",
        "--legacy-sqlite", str(legacy),
        "--journal-path", str(journal),
        "--source-namespace", "fixture/source",
        "--report-path", str(report),
        "preflight",
    ])

    with pytest.raises(ValueError, match="report must not replace a database"):
        cli._service(arguments)


@pytest.mark.parametrize(
    "protected_name",
    [
        "legacy.sqlite-wal",
        "legacy.sqlite-shm",
        "legacy.sqlite-journal",
        ".legacy.sqlite.reverse-sync.lock",
        "journal.sqlite-wal",
        "journal.sqlite-shm",
        "journal.sqlite-journal",
        ".journal.sqlite.lock",
    ],
)
def test_cli_rejects_a_report_that_would_replace_a_sidecar_or_lock(
    tmp_path: Path,
    protected_name: str,
):
    arguments = cli.build_parser().parse_args([
        "--postgres-dsn", "postgresql://redacted.invalid/mranked",
        "--legacy-sqlite", str(tmp_path / "legacy.sqlite"),
        "--journal-path", str(tmp_path / "journal.sqlite"),
        "--source-namespace", "fixture/source",
        "--report-path", str(tmp_path / protected_name),
        "preflight",
    ])

    with pytest.raises(ValueError, match="sidecar, or lock"):
        cli._service(arguments)


@pytest.mark.parametrize("legacy_is_lock", [False, True])
def test_cli_rejects_cross_collisions_between_database_reserved_paths(
    tmp_path: Path,
    legacy_is_lock: bool,
):
    if legacy_is_lock:
        legacy = tmp_path / ".journal.sqlite.lock"
        journal = tmp_path / "journal.sqlite"
    else:
        legacy = tmp_path / "legacy.sqlite"
        journal = tmp_path / "legacy.sqlite-wal"
    arguments = cli.build_parser().parse_args([
        "--postgres-dsn", "postgresql://redacted.invalid/mranked",
        "--legacy-sqlite", str(legacy),
        "--journal-path", str(journal),
        "--source-namespace", "fixture/source",
        "preflight",
    ])

    with pytest.raises(ValueError, match="reserved paths must be distinct"):
        cli._service(arguments)


def test_cli_requires_legacy_database_and_journal_to_be_distinct(tmp_path: Path):
    shared = tmp_path / "state.sqlite"
    arguments = cli.build_parser().parse_args([
        "--postgres-dsn", "postgresql://redacted.invalid/mranked",
        "--legacy-sqlite", str(shared),
        "--journal-path", str(shared),
        "--source-namespace", "fixture/source",
        "preflight",
    ])

    with pytest.raises(ValueError, match="must be distinct"):
        cli._service(arguments)


@pytest.mark.parametrize("path_kind", ["legacy", "journal", "report"])
def test_cli_rejects_paths_that_traverse_a_symlinked_ancestor(
    tmp_path: Path,
    path_kind: str,
):
    real_directory = tmp_path / "real"
    real_directory.mkdir()
    linked_directory = tmp_path / "linked"
    linked_directory.symlink_to(real_directory, target_is_directory=True)
    legacy = tmp_path / "legacy.sqlite"
    journal = tmp_path / "journal.sqlite"
    report: Path | None = None
    if path_kind == "legacy":
        legacy = linked_directory / "legacy.sqlite"
    elif path_kind == "journal":
        journal = linked_directory / "journal.sqlite"
    else:
        report = linked_directory / "report.json"
    argv = [
        "--postgres-dsn", "postgresql://redacted.invalid/mranked",
        "--legacy-sqlite", str(legacy),
        "--journal-path", str(journal),
        "--source-namespace", "fixture/source",
    ]
    if report is not None:
        argv.extend(("--report-path", str(report)))
    argv.append("preflight")
    arguments = cli.build_parser().parse_args(argv)

    with pytest.raises(ValueError, match="must not traverse symlinks"):
        cli._validated_paths(arguments)


def test_atomic_report_refuses_to_follow_a_symlink(tmp_path: Path):
    destination = tmp_path / "real.json"
    destination.write_text("do not replace\n", encoding="utf-8")
    link = tmp_path / "report.json"
    link.symlink_to(destination)

    with pytest.raises(ValueError, match="must not be a symlink"):
        cli._atomic_report(link, {"status": "pass"})
    assert destination.read_text(encoding="utf-8") == "do not replace\n"


class _FakeConnection:
    def __init__(self) -> None:
        self.executed: list[str] = []

    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield

    def execute(self, statement: str) -> None:
        self.executed.append(statement)


class _FakeSource:
    source_namespace = "fixture/source"

    def __init__(self) -> None:
        self.s_final_value = {
            "id": UUID("f34650c5-4161-44d6-9e5a-09d7f25c0874"),
            "source_sha256": "b" * 64,
        }
        self.visible_revisions: tuple[Revision, ...] = (_revision(1),)
        self.connection = _FakeConnection()

    def preflight(self) -> dict[str, bool]:
        return {
            "aliasMappingsUnambiguous": True,
            "singlePrimaryIdentity": True,
        }

    @contextmanager
    def connect(self) -> Iterator[_FakeConnection]:
        yield self.connection

    @contextmanager
    def drain_lock(self) -> Iterator[_FakeConnection]:
        yield self.connection

    def s_final(self, _connection: _FakeConnection) -> dict[str, Any]:
        return dict(self.s_final_value)

    def revisions(self, _connection: _FakeConnection) -> tuple[Revision, ...]:
        return self.visible_revisions

    def build_plan(
        self,
        _connection: _FakeConnection,
        *,
        baseline_revision_ids: Sequence[int],
        started_at: datetime,
    ) -> SyncPlan:
        baseline = tuple(baseline_revision_ids)
        baseline_set = set(baseline)
        delta = tuple(
            revision
            for revision in self.visible_revisions
            if revision.id not in baseline_set
        )
        return SyncPlan(
            baseline_revision_ids=baseline,
            revision_ids=tuple(revision.id for revision in delta),
            revisions=delta,
            accounts=(),
            publications=(),
            snapshots=(),
            collection_runs=(),
            generated_at=started_at,
        )

    def reserve_publication_aliases(
        self,
        _connection: _FakeConnection,
        _publications: Sequence[Mapping[str, Any]],
        *,
        sqlite_maximums: Mapping[str, int],
    ) -> dict[UUID, tuple[str, int]]:
        assert sqlite_maximums == {"posts": 0, "platform_posts": 0}
        return {}


class _FakeTarget:
    def __init__(self, identity_sha256: str = "d" * 64) -> None:
        self.identity_sha256 = identity_sha256
        self.applied: list[str] = []
        self.verified: list[str] = []
        self.durability_calls = 0

    def identity(self) -> str:
        return self.identity_sha256

    def preflight(self) -> dict[str, Any]:
        return {"quickCheck": "ok", "freeBytes": 1_000_000}

    def maximum_legacy_ids(self) -> dict[str, int]:
        return {"posts": 0, "platform_posts": 0}

    def apply(
        self,
        plan: SyncPlan,
        _aliases: Mapping[UUID, tuple[str, int]],
    ) -> dict[str, int]:
        self.applied.append(plan.digest)
        return plan.counts()

    def verify(
        self,
        plan: SyncPlan,
        _aliases: Mapping[UUID, tuple[str, int]],
    ) -> dict[str, Any]:
        self.verified.append(plan.digest)
        return {"matches": True, "planSha256": plan.digest}

    def durability_barrier(self) -> dict[str, Any]:
        self.durability_calls += 1
        return {"quickCheck": "ok"}


def test_production_target_derives_one_shared_lock_across_different_journals(
    tmp_path: Path,
):
    source = _FakeSource()
    target_path = tmp_path / "legacy.sqlite"
    target = LegacySqliteTarget(target_path, "fixture/source", min_free_bytes=0)
    first = ReverseSyncService(
        source,  # type: ignore[arg-type]
        target,
        ReverseSyncJournal(tmp_path / "journal-a" / "state.sqlite"),
    )
    second = ReverseSyncService(
        source,  # type: ignore[arg-type]
        target,
        ReverseSyncJournal(tmp_path / "journal-b" / "state.sqlite"),
    )
    expected = tmp_path / ".legacy.sqlite.reverse-sync.lock"

    assert first._lock_path == expected
    assert second._lock_path == expected
    with first._operation_lock():
        with pytest.raises(RuntimeError, match="another reverse-sync operation"):
            with second._operation_lock():
                pytest.fail("a second journal acquired the target's operation lock")


def test_service_enforces_start_drain_verify_stop_state_machine(tmp_path: Path):
    source = _FakeSource()
    target = _FakeTarget()
    journal = ReverseSyncJournal(tmp_path / "reverse-sync.sqlite")
    service = ReverseSyncService(source, target, journal)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="transition is not allowed"):
        service.verify()

    started = service.start(
        rollback_window_hours=24,
        operator="migration-operator",
        ticket="CHG-42",
    )
    assert started["status"] == "active"
    assert started["idempotent"] is False
    assert journal.revision_ids("baseline_revision") == (1,)

    repeated = service.start(
        rollback_window_hours=24,
        operator="migration-operator",
        ticket="CHG-42",
    )
    assert repeated["status"] == "active"
    assert repeated["idempotent"] is True
    with pytest.raises(RuntimeError, match="idempotency key"):
        service.start(
            rollback_window_hours=24,
            operator="different-operator",
            ticket="CHG-42",
        )

    source.visible_revisions = (_revision(1), _revision(2))
    drained = service.drain(operator="migration-operator", ticket="CHG-42")
    assert drained["status"] == "drained"
    assert drained["fixedRevisionCount"] == 1
    assert journal.revision_ids("drain_revision") == (2,)

    verified = service.verify()
    assert verified["status"] == "verified"
    stopped = service.stop()
    assert stopped["status"] == "stopped"
    assert stopped["idempotent"] is False
    assert service.stop()["idempotent"] is True
    assert journal.load_state().status == "stopped"  # type: ignore[union-attr]
    assert len(target.applied) == 1
    assert len(target.verified) == 2
    assert target.durability_calls == 2
    assert source.connection.executed == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
    ]


def test_repeated_start_rejects_a_different_rollback_window(tmp_path: Path):
    source = _FakeSource()
    target = _FakeTarget()
    journal = ReverseSyncJournal(tmp_path / "reverse-sync.sqlite")
    service = ReverseSyncService(source, target, journal)  # type: ignore[arg-type]
    service.start(
        rollback_window_hours=24,
        operator="migration-operator",
        ticket="CHG-42",
    )
    original = journal.load_state()

    with pytest.raises(RuntimeError, match="rollback window|idempotency"):
        service.start(
            rollback_window_hours=48,
            operator="migration-operator",
            ticket="CHG-42",
        )
    assert journal.load_state() == original


def test_repeated_drain_validates_fixed_plan_before_mutating_legacy(
    tmp_path: Path,
):
    source = _FakeSource()
    target = _FakeTarget()
    journal = ReverseSyncJournal(tmp_path / "reverse-sync.sqlite")
    service = ReverseSyncService(source, target, journal)  # type: ignore[arg-type]
    service.start(
        rollback_window_hours=24,
        operator="migration-operator",
        ticket="CHG-42",
    )
    source.visible_revisions = (_revision(1), _revision(2))
    service.drain(operator="migration-operator", ticket="CHG-42")
    fixed_state = journal.load_state()
    fixed_checkpoint = journal.applied_checkpoint()

    source.visible_revisions = (_revision(1), _revision(2), _revision(3))
    with pytest.raises(RuntimeError, match="fixed drain|target changed"):
        service.drain(operator="migration-operator", ticket="CHG-42")

    assert len(target.applied) == 1
    assert target.durability_calls == 1
    assert journal.load_state() == fixed_state
    assert journal.applied_checkpoint() == fixed_checkpoint


def test_status_rejects_a_missing_baseline_revision(tmp_path: Path):
    source = _FakeSource()
    journal = ReverseSyncJournal(tmp_path / "reverse-sync.sqlite")
    service = ReverseSyncService(source, _FakeTarget(), journal)  # type: ignore[arg-type]
    service.start(
        rollback_window_hours=24,
        operator="migration-operator",
        ticket="CHG-42",
    )
    source.visible_revisions = ()

    with pytest.raises(RuntimeError, match="baseline.*visible"):
        service.status()


def test_status_rejects_an_applied_revision_outside_the_visible_delta(
    tmp_path: Path,
):
    source = _FakeSource()
    journal = ReverseSyncJournal(tmp_path / "reverse-sync.sqlite")
    service = ReverseSyncService(source, _FakeTarget(), journal)  # type: ignore[arg-type]
    service.start(
        rollback_window_hours=24,
        operator="migration-operator",
        ticket="CHG-42",
    )
    source.visible_revisions = (_revision(1), _revision(2))
    journal.record_applied((3,), "c" * 64)

    with pytest.raises(RuntimeError, match="applied.*visible"):
        service.status()


def test_journal_cannot_be_reused_with_a_different_legacy_target(tmp_path: Path):
    source = _FakeSource()
    journal = ReverseSyncJournal(tmp_path / "reverse-sync.sqlite")
    first_target = _FakeTarget("d" * 64)
    ReverseSyncService(source, first_target, journal).start(  # type: ignore[arg-type]
        rollback_window_hours=24,
        operator="migration-operator",
        ticket="CHG-42",
    )
    assert journal.legacy_target_identity() == "d" * 64

    replacement_target = _FakeTarget("e" * 64)
    replacement_service = ReverseSyncService(  # type: ignore[arg-type]
        source,
        replacement_target,
        journal,
    )
    with pytest.raises(RuntimeError, match="legacy target binding changed"):
        replacement_service.preflight()
    assert replacement_target.applied == []
    assert journal.legacy_target_identity() == "d" * 64


def test_once_fails_closed_after_rollback_deadline(tmp_path: Path):
    source = _FakeSource()
    target = _FakeTarget()
    journal = ReverseSyncJournal(tmp_path / "reverse-sync.sqlite")
    service = ReverseSyncService(source, target, journal)  # type: ignore[arg-type]
    service.start(
        rollback_window_hours=1,
        operator="migration-operator",
        ticket="CHG-42",
    )
    state = journal.load_state()
    assert state is not None
    expired_deadline = datetime.now(UTC) - timedelta(seconds=1)
    journal.save_state(
        replace(
            state,
            started_at=expired_deadline - timedelta(hours=1),
            rollback_deadline=expired_deadline,
        ),
        "test-expired",
    )

    with pytest.raises(RuntimeError, match="window has expired"):
        service.once()
    assert target.applied == []
