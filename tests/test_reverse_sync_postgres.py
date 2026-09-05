from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID, uuid4

import pytest

from collector_target.model import (
    AccountRef,
    CollectionContext,
    HistoryCompleteness,
    IdentityCandidate,
    IdentityRole,
    ObservationQuality,
    Platform,
    RawAccountObservation,
    RawCollectionBatch,
    RawPublication,
)
from collector_target.normalize import CanonicalNormalizer
from collector_target.repository import PostgresCollectorRepository
from migration.bridge.fixture import build_golden_fixture
from migration.bridge.model import BridgeOptions
from migration.bridge.service import BridgeService
from migration.bridge.source import LegacySource, create_online_backup
from migration.bridge.target import PostgresTarget


POSTGRES_DSN = os.environ.get("MRANKED_TEST_REVERSE_SYNC_POSTGRES_DSN")
ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = ROOT / "backend/src/main/resources/db/migration"
LOCAL_REHEARSAL_ENVIRONMENT = "disposable-postgresql-integration"
EXPECTED_FLYWAY_MIGRATIONS = (
    (
        "1",
        "V1__target_baseline.sql",
        "dc0ded29c5b7b42860dbabd04988c1803900685dc074c25adf5969e8be8d9fb1",
        -1636077697,
    ),
    (
        "2",
        "V2__rebuild_core_projections.sql",
        "113e94524c6617bf59ab7dc2760615bf9c6d10538c12290400e15f85df16c7dd",
        839607018,
    ),
    (
        "3",
        "V3__collector_observation_times_and_identity_grants.sql",
        "5233f98d3b39db74a449b1e9852f252def1606c5982e87d40ec366275d388ad1",
        -1456658399,
    ),
    (
        "4",
        "V4__admin_collection_run_status_grants.sql",
        "d5af14bfc692e9e3b57ed257b3632fbc616cb65ba47babb2aebb1d7dea5b7e82",
        1318350062,
    ),
    (
        "5",
        "V5__legacy_activity_period_projection.sql",
        "d56c124e2d68eb9897d3fe9d10bde0adf730ea02b84e0d7ec09660775438ea41",
        -1313754193,
    ),
    (
        "6",
        "V6__comparison_valid_observation_hourly_projection.sql",
        "4ac99091046d40345c7024d3fab96ceb779fafb836c18c6a750f748f7bd29c64",
        -290358219,
    ),
    (
        "7",
        "V7__activity_rating_read_grants.sql",
        "95244a71a992fb8d9de387622224ddb52365120ac47c4d0cf4cbb20f4e36f0eb",
        -1228913579,
    ),
    (
        "8",
        "V8__legacy_overview_projection.sql",
        "dc855dde66a705808e1565e3f56c4555995d370805cee68ee9293ae7fa0aec9c",
        -574188650,
    ),
)
LOCAL_RELEASE_MANIFEST_SHA256 = hashlib.sha256(
    b"disposable-postgresql-integration:unbound-release"
).hexdigest()
PROVENANCE_MODULE_NAMES = (
    "collector_target.model",
    "migration.bridge.service",
    "operations.reverse_sync.service",
)


def _dsn(name: str, fallback: str) -> str:
    return os.environ.get(name, fallback).strip()


def _dsn_contains_password(dsn: str) -> bool:
    normalized = str(dsn).strip()
    if not normalized:
        return False
    if re.search(r"(?:^|\s)password\s*=", normalized, flags=re.IGNORECASE):
        return True
    if "://" not in normalized:
        return False
    try:
        parsed = urlsplit(normalized)
        return parsed.password is not None or any(
            key.strip().casefold() == "password"
            for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
        )
    except ValueError:
        return True


def _stable_regular_file_digest(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AssertionError(f"release manifest entry is not a stable regular file: {path}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise AssertionError(f"release manifest entry is not a regular file: {path}")
        if before.st_mode & 0o022:
            raise AssertionError(f"release manifest entry is group/world writable: {path}")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
        identity = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        if identity(before) != identity(after):
            raise AssertionError(f"release manifest entry changed while hashing: {path}")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _read_stable_manifest(path: Path) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AssertionError("release SHA256SUMS must be a regular non-symlink file") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_mode & 0o022:
            raise AssertionError(
                "release SHA256SUMS must be a non-group/world-writable regular file"
            )
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise AssertionError("release SHA256SUMS changed while it was read")
        return b"".join(chunks), after
    finally:
        os.close(descriptor)


def _verified_release_manifest(release_root: Path) -> str:
    manifest_path = release_root / "SHA256SUMS"
    manifest_bytes, before = _read_stable_manifest(manifest_path)
    try:
        lines = manifest_bytes.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise AssertionError("release SHA256SUMS must be ASCII") from exc
    if not lines:
        raise AssertionError("release SHA256SUMS must not be empty")

    entries: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(
            r"([0-9a-f]{64}) [ *]([A-Za-z0-9._+@%/-]+)",
            line,
        )
        if match is None:
            raise AssertionError("release SHA256SUMS contains a malformed entry")
        expected_sha256, relative_name = match.groups()
        relative_path = Path(relative_name)
        if (
            relative_path.is_absolute()
            or any(part in {"", ".", ".."} for part in relative_path.parts)
            or relative_name in entries
            or relative_name == "SHA256SUMS"
        ):
            raise AssertionError("release SHA256SUMS contains an unsafe or duplicate path")
        entries[relative_name] = expected_sha256

    required_test = "tests/test_reverse_sync_postgres.py"
    if required_test not in entries:
        raise AssertionError("release SHA256SUMS does not bind the rehearsal test")

    actual_files: set[str] = set()
    for current_root, directory_names, file_names in os.walk(
        release_root,
        followlinks=False,
    ):
        current_path = Path(current_root)
        directory_stat = current_path.stat()
        if not stat.S_ISDIR(directory_stat.st_mode) or directory_stat.st_mode & 0o022:
            raise AssertionError(
                "release tree contains a group/world-writable directory"
            )
        directory_names[:] = [
            name for name in directory_names if not (current_path / name).is_symlink()
        ]
        for file_name in file_names:
            candidate = current_path / file_name
            if candidate.is_symlink() or not candidate.is_file():
                continue
            relative_name = candidate.relative_to(release_root).as_posix()
            if relative_name != "SHA256SUMS":
                actual_files.add(relative_name)
    if set(entries) != actual_files:
        raise AssertionError(
            "release SHA256SUMS does not cover exactly every regular release file"
        )

    for relative_name, expected_sha256 in entries.items():
        candidate = release_root / relative_name
        resolved_candidate = candidate.resolve(strict=True)
        try:
            resolved_candidate.relative_to(release_root)
        except ValueError as exc:
            raise AssertionError("release SHA256SUMS path escapes the release root") from exc
        if candidate.is_symlink() or resolved_candidate != candidate:
            raise AssertionError("release SHA256SUMS entry traverses a symlink")
        if _stable_regular_file_digest(candidate) != expected_sha256:
            raise AssertionError("release SHA256SUMS verification failed")

    _manifest_bytes_after, after = _read_stable_manifest(manifest_path)
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise AssertionError("release SHA256SUMS changed during verification")
    return hashlib.sha256(manifest_bytes).hexdigest()


def _production_release_provenance(
    configured_root: str,
    *,
    execution_root: Path | None = None,
    python_prefix: Path | None = None,
    module_origins: Sequence[Path] | None = None,
    bytecode_writes_disabled: bool | None = None,
) -> tuple[str, str]:
    raw_root = configured_root.strip()
    if not raw_root or raw_root.casefold().startswith("replace-with-"):
        raise AssertionError("production-like rehearsal requires a real release root")
    supplied_root = Path(raw_root)
    if not supplied_root.is_absolute():
        raise AssertionError("production-like release root must be absolute")
    release_root = supplied_root.resolve(strict=True)
    if supplied_root != release_root or supplied_root.is_symlink():
        raise AssertionError("production-like release root must be canonical and non-symlinked")
    directory = release_root
    while True:
        directory_stat = directory.stat()
        if (
            not stat.S_ISDIR(directory_stat.st_mode)
            or directory_stat.st_mode & 0o022
            or directory.is_symlink()
        ):
            raise AssertionError(
                "production-like release root must have a canonical, "
                "non-group/world-writable directory chain"
            )
        if directory == directory.parent:
            break
        directory = directory.parent

    release_id = release_root.name
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", release_id)
        or release_id.casefold().startswith("replace-with-")
    ):
        raise AssertionError("production-like release directory name is not a safe release id")

    actual_execution_root = (execution_root or ROOT).resolve(strict=True)
    if actual_execution_root != release_root:
        raise AssertionError("rehearsal test is not executing from the configured release root")

    actual_python_prefix = (python_prefix or Path(sys.prefix)).resolve(strict=True)
    if actual_python_prefix != release_root / ".venv":
        raise AssertionError("rehearsal Python environment is not the release .venv")
    if not (
        sys.dont_write_bytecode
        if bytecode_writes_disabled is None
        else bytecode_writes_disabled
    ):
        raise AssertionError(
            "production-like rehearsal requires PYTHONDONTWRITEBYTECODE=1"
        )

    origins = module_origins
    if origins is None:
        origins = []
        for module_name in PROVENANCE_MODULE_NAMES:
            module = importlib.import_module(module_name)
            origin = getattr(module, "__file__", None)
            if not origin:
                raise AssertionError(f"module origin is unavailable: {module_name}")
            origins.append(Path(origin))
    for origin in origins:
        resolved_origin = origin.resolve(strict=True)
        try:
            resolved_origin.relative_to(release_root)
        except ValueError as exc:
            raise AssertionError("rehearsal module origin is outside the release root") from exc

    manifest_sha256 = _verified_release_manifest(release_root)
    return release_id, manifest_sha256


def _require_password_free_production_dsns(
    environment: str,
    dsns: Mapping[str, str],
) -> None:
    if environment != "production-like":
        return
    unsafe_names = sorted(name for name, dsn in dsns.items() if _dsn_contains_password(dsn))
    if unsafe_names:
        raise AssertionError(
            "production-like rehearsal DSNs must use pgpass and omit passwords: "
            + ", ".join(unsafe_names)
        )


def _validated_flyway_manifest(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if len(rows) == 9:
        marker = rows[0]
        assert {
            "installed_rank": marker["installed_rank"],
            "version": marker["version"],
            "description": marker["description"],
            "type": marker["type"],
            "script": marker["script"],
            "checksum": marker["checksum"],
            "success": marker["success"],
        } == {
            "installed_rank": 0,
            "version": None,
            "description": "<< Flyway Schema Creation >>",
            "type": "SCHEMA",
            "script": '"flyway"',
            "checksum": None,
            "success": True,
        }, "Flyway history contains an unexpected schema/baseline marker"
        versioned_rows = rows[1:]
    else:
        assert len(rows) == 8, (
            "Flyway history must contain exactly V1-V8, optionally preceded "
            "by the one allowed schema marker"
        )
        versioned_rows = rows

    manifest: list[dict[str, Any]] = []
    for installed_rank, (row, expected) in enumerate(
        zip(versioned_rows, EXPECTED_FLYWAY_MIGRATIONS, strict=True),
        start=1,
    ):
        version, script, _sha256, checksum = expected
        assert {
            "installed_rank": row["installed_rank"],
            "version": str(row["version"]),
            "type": row["type"],
            "script": row["script"],
            "checksum": row["checksum"],
            "success": row["success"],
        } == {
            "installed_rank": installed_rank,
            "version": version,
            "type": "SQL",
            "script": script,
            "checksum": checksum,
            "success": True,
        }, "Flyway history contains an unexpected versioned migration"
        manifest.append({
            "version": version,
            "script": script,
            "checksum": checksum,
            "success": True,
        })
    return manifest


def _rehearsal_context(default_source_namespace: str) -> dict[str, str]:
    environment = os.environ.get(
        "MRANKED_TEST_REVERSE_SYNC_ENVIRONMENT",
        LOCAL_REHEARSAL_ENVIRONMENT,
    ).strip()
    if environment not in {LOCAL_REHEARSAL_ENVIRONMENT, "production-like"}:
        raise AssertionError("reverse-sync rehearsal environment is unsupported")

    production_names = {
        "releaseRoot": "MRANKED_TEST_REVERSE_SYNC_RELEASE_ROOT",
        "operator": "MRANKED_TEST_REVERSE_SYNC_OPERATOR",
        "changeTicket": "MRANKED_TEST_REVERSE_SYNC_APPROVAL_TICKET",
        "sourceNamespace": "MRANKED_TEST_REVERSE_SYNC_SOURCE_NAMESPACE",
    }
    if environment == "production-like":
        missing = [
            env_name
            for env_name in production_names.values()
            if not os.environ.get(env_name, "").strip()
        ]
        if missing:
            raise AssertionError(
                "production-like rehearsal requires explicit context: "
                + ", ".join(sorted(missing))
            )

    if environment == "production-like":
        release_id, release_manifest_sha256 = _production_release_provenance(
            os.environ[production_names["releaseRoot"]]
        )
    else:
        release_id = "local-unbound"
        release_manifest_sha256 = LOCAL_RELEASE_MANIFEST_SHA256

    context = {
        "environment": environment,
        "releaseId": release_id,
        "releaseManifestSha256": release_manifest_sha256,
        "operator": os.environ.get(
            production_names["operator"], "pytest-reverse-sync"
        ).strip(),
        "changeTicket": os.environ.get(
            production_names["changeTicket"], "TEST-WRITER-GATE-W"
        ).strip(),
        "sourceNamespace": os.environ.get(
            production_names["sourceNamespace"], default_source_namespace
        ).strip(),
    }
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", context["releaseId"]):
        raise AssertionError("reverse-sync rehearsal release id is unsafe")
    if not re.fullmatch(r"[0-9a-f]{64}", context["releaseManifestSha256"]):
        raise AssertionError("reverse-sync release manifest SHA-256 is invalid")
    if any(not context[name] for name in ("operator", "changeTicket", "sourceNamespace")):
        raise AssertionError("reverse-sync rehearsal provenance must be non-empty")
    if environment == "production-like" and any(
        context[name].casefold().startswith("replace-with-")
        for name in ("operator", "changeTicket", "sourceNamespace")
    ):
        raise AssertionError("production-like rehearsal provenance contains a placeholder")
    return context


def _write_new_private_file(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
        temporary.unlink()
        os.chmod(path, 0o600)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_descriptor = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_rehearsal_evidence(report: Mapping[str, Any]) -> None:
    raw_path = os.environ.get("MRANKED_TEST_REVERSE_SYNC_REPORT_PATH", "").strip()
    if not raw_path:
        return

    path = Path(os.path.abspath(Path(raw_path).expanduser()))
    checksum_path = Path(f"{path}.sha256")
    if any(
        candidate.is_symlink()
        for candidate in (path, checksum_path, *path.parents)
    ):
        raise AssertionError(
            "reverse-sync rehearsal report path must not traverse symlinks"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or checksum_path.exists():
        raise FileExistsError(
            "reverse-sync rehearsal report and sidecar paths must be new for every run"
        )

    payload = (
        json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    checksum = hashlib.sha256(payload).hexdigest()
    _write_new_private_file(path, payload)
    _write_new_private_file(
        checksum_path,
        f"{checksum}  {path.name}\n".encode("ascii"),
    )


def test_rehearsal_evidence_writer_is_private_and_never_clobbers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path = tmp_path / "evidence.json"
    monkeypatch.setenv(
        "MRANKED_TEST_REVERSE_SYNC_REPORT_PATH",
        str(report_path),
    )
    evidence = {"status": "pass", "proof": {"count": 1}}

    _write_rehearsal_evidence(evidence)

    assert json.loads(report_path.read_text(encoding="utf-8")) == evidence
    assert report_path.stat().st_mode & 0o777 == 0o600
    checksum_path = Path(f"{report_path}.sha256")
    checksum_record = checksum_path.read_text(encoding="ascii").split()
    assert checksum_record == [
        hashlib.sha256(report_path.read_bytes()).hexdigest(),
        report_path.name,
    ]
    assert checksum_path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError, match="must be new"):
        _write_rehearsal_evidence({"status": "pass", "proof": {"count": 2}})
    assert json.loads(report_path.read_text(encoding="utf-8")) == evidence


def test_rehearsal_evidence_writer_rejects_symlinked_ancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_directory = tmp_path / "real"
    real_directory.mkdir()
    symlinked_directory = tmp_path / "linked"
    symlinked_directory.symlink_to(real_directory, target_is_directory=True)
    monkeypatch.setenv(
        "MRANKED_TEST_REVERSE_SYNC_REPORT_PATH",
        str(symlinked_directory / "evidence.json"),
    )

    with pytest.raises(AssertionError, match="must not traverse symlinks"):
        _write_rehearsal_evidence({"status": "pass"})

    assert tuple(real_directory.iterdir()) == ()


def test_rehearsal_evidence_writer_never_clobbers_existing_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path = tmp_path / "evidence.json"
    checksum_path = Path(f"{report_path}.sha256")
    checksum_path.write_text("retained approval\n", encoding="utf-8")
    monkeypatch.setenv(
        "MRANKED_TEST_REVERSE_SYNC_REPORT_PATH",
        str(report_path),
    )

    with pytest.raises(FileExistsError, match="must be new"):
        _write_rehearsal_evidence({"status": "pass"})

    assert not report_path.exists()
    assert checksum_path.read_text(encoding="utf-8") == "retained approval\n"


def test_rehearsal_context_defaults_to_non_approvable_local_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "MRANKED_TEST_REVERSE_SYNC_ENVIRONMENT",
        "MRANKED_TEST_REVERSE_SYNC_RELEASE_ROOT",
        "MRANKED_TEST_REVERSE_SYNC_OPERATOR",
        "MRANKED_TEST_REVERSE_SYNC_APPROVAL_TICKET",
        "MRANKED_TEST_REVERSE_SYNC_SOURCE_NAMESPACE",
    ):
        monkeypatch.delenv(name, raising=False)

    context = _rehearsal_context("pytest-reverse-sync-local")

    assert context == {
        "environment": LOCAL_REHEARSAL_ENVIRONMENT,
        "releaseId": "local-unbound",
        "releaseManifestSha256": LOCAL_RELEASE_MANIFEST_SHA256,
        "operator": "pytest-reverse-sync",
        "changeTicket": "TEST-WRITER-GATE-W",
        "sourceNamespace": "pytest-reverse-sync-local",
    }


def test_flyway_history_allows_exact_v1_v8_with_optional_schema_marker() -> None:
    rows: list[dict[str, Any]] = [{
        "installed_rank": 0,
        "version": None,
        "description": "<< Flyway Schema Creation >>",
        "type": "SCHEMA",
        "script": '"flyway"',
        "checksum": None,
        "success": True,
    }]
    rows.extend(
        {
            "installed_rank": rank,
            "version": version,
            "description": script,
            "type": "SQL",
            "script": script,
            "checksum": checksum,
            "success": True,
        }
        for rank, (version, script, _sha256, checksum) in enumerate(
            EXPECTED_FLYWAY_MIGRATIONS,
            start=1,
        )
    )

    expected_manifest = [
        {
            "version": version,
            "script": script,
            "checksum": checksum,
            "success": True,
        }
        for version, script, _sha256, checksum in EXPECTED_FLYWAY_MIGRATIONS
    ]
    assert _validated_flyway_manifest(rows) == expected_manifest
    assert _validated_flyway_manifest(rows[1:]) == expected_manifest

    unexpected = [dict(row) for row in rows]
    unexpected[0]["type"] = "BASELINE"
    with pytest.raises(AssertionError, match="unexpected schema/baseline"):
        _validated_flyway_manifest(unexpected)

    with pytest.raises(AssertionError, match="exactly V1-V8"):
        _validated_flyway_manifest([*rows, dict(rows[-1])])


def test_production_like_rehearsal_context_requires_every_explicit_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MRANKED_TEST_REVERSE_SYNC_ENVIRONMENT", "production-like")
    required = {
        "MRANKED_TEST_REVERSE_SYNC_RELEASE_ROOT": "/opt/m-ranked/releases/release-2026-09-05",
        "MRANKED_TEST_REVERSE_SYNC_OPERATOR": "rehearsal-operator",
        "MRANKED_TEST_REVERSE_SYNC_APPROVAL_TICKET": "GATE-W-APPROVAL",
        "MRANKED_TEST_REVERSE_SYNC_SOURCE_NAMESPACE": "m-ranked-production",
    }
    for name in required:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(AssertionError, match="requires explicit context"):
        _rehearsal_context("ignored-local-default")

    for name, value in required.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        sys.modules[__name__],
        "_production_release_provenance",
        lambda _root: ("release-2026-09-05", "a" * 64),
    )
    assert _rehearsal_context("ignored-local-default") == {
        "environment": "production-like",
        "releaseId": "release-2026-09-05",
        "releaseManifestSha256": "a" * 64,
        "operator": "rehearsal-operator",
        "changeTicket": "GATE-W-APPROVAL",
        "sourceNamespace": "m-ranked-production",
    }


def _release_provenance_fixture(tmp_path: Path) -> tuple[Path, tuple[Path, ...]]:
    release_root = tmp_path / "release-2026-09-05"
    files = {
        "tests/test_reverse_sync_postgres.py": b"rehearsal test\n",
        "collector_target/model.py": b"collector model\n",
        "migration/bridge/service.py": b"bridge service\n",
        "operations/reverse_sync/service.py": b"reverse service\n",
    }
    for relative_name, contents in files.items():
        path = release_root / relative_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        path.chmod(0o644)
    (release_root / ".venv").mkdir()
    manifest = "".join(
        f"{hashlib.sha256(contents).hexdigest()}  {relative_name}\n"
        for relative_name, contents in sorted(files.items())
    )
    (release_root / "SHA256SUMS").write_text(manifest, encoding="ascii")
    (release_root / "SHA256SUMS").chmod(0o644)
    release_root.chmod(0o755)
    origins = tuple(
        release_root / relative_name
        for relative_name in (
            "collector_target/model.py",
            "migration/bridge/service.py",
            "operations/reverse_sync/service.py",
        )
    )
    return release_root, origins


def test_production_release_provenance_is_derived_from_verified_root(
    tmp_path: Path,
) -> None:
    release_root, origins = _release_provenance_fixture(tmp_path)

    assert _production_release_provenance(
        str(release_root),
        execution_root=release_root,
        python_prefix=release_root / ".venv",
        module_origins=origins,
        bytecode_writes_disabled=True,
    ) == (
        release_root.name,
        hashlib.sha256((release_root / "SHA256SUMS").read_bytes()).hexdigest(),
    )


def test_production_release_provenance_rejects_unbound_or_mutable_inputs(
    tmp_path: Path,
) -> None:
    release_root, origins = _release_provenance_fixture(tmp_path)
    arguments = {
        "execution_root": release_root,
        "python_prefix": release_root / ".venv",
        "module_origins": origins,
        "bytecode_writes_disabled": True,
    }

    with pytest.raises(AssertionError, match="not executing"):
        _production_release_provenance(
            str(release_root),
            **{**arguments, "execution_root": tmp_path},
        )
    with pytest.raises(AssertionError, match="not the release .venv"):
        _production_release_provenance(
            str(release_root),
            **{**arguments, "python_prefix": tmp_path},
        )
    with pytest.raises(AssertionError, match="PYTHONDONTWRITEBYTECODE"):
        _production_release_provenance(
            str(release_root),
            **{**arguments, "bytecode_writes_disabled": False},
        )
    with pytest.raises(AssertionError, match="module origin is outside"):
        _production_release_provenance(
            str(release_root),
            **{**arguments, "module_origins": (*origins[:-1], tmp_path)},
        )

    linked_root = tmp_path / "linked-release"
    linked_root.symlink_to(release_root, target_is_directory=True)
    with pytest.raises(AssertionError, match="canonical and non-symlinked"):
        _production_release_provenance(str(linked_root), **arguments)

    unlisted = release_root / "unlisted.py"
    unlisted.write_text("not in SHA256SUMS\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="cover exactly every regular"):
        _production_release_provenance(str(release_root), **arguments)
    unlisted.unlink()

    mutable_directory = release_root / "collector_target"
    mutable_directory.chmod(0o775)
    with pytest.raises(AssertionError, match="group/world-writable directory"):
        _production_release_provenance(str(release_root), **arguments)
    mutable_directory.chmod(0o755)

    changed_file = release_root / "collector_target/model.py"
    changed_file.write_text("changed after packaging\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="verification failed"):
        _production_release_provenance(str(release_root), **arguments)


def test_production_like_rehearsal_rejects_placeholders_and_password_dsns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MRANKED_TEST_REVERSE_SYNC_ENVIRONMENT", "production-like")
    monkeypatch.setenv(
        "MRANKED_TEST_REVERSE_SYNC_RELEASE_ROOT",
        "/opt/m-ranked/releases/release-2026-09-05",
    )
    monkeypatch.setenv("MRANKED_TEST_REVERSE_SYNC_OPERATOR", "replace-with-operator")
    monkeypatch.setenv("MRANKED_TEST_REVERSE_SYNC_APPROVAL_TICKET", "GATE-W-APPROVAL")
    monkeypatch.setenv("MRANKED_TEST_REVERSE_SYNC_SOURCE_NAMESPACE", "production")
    monkeypatch.setattr(
        sys.modules[__name__],
        "_production_release_provenance",
        lambda _root: ("release-2026-09-05", "a" * 64),
    )

    with pytest.raises(AssertionError, match="placeholder"):
        _rehearsal_context("ignored")

    with pytest.raises(AssertionError, match="must use pgpass") as captured:
        _require_password_free_production_dsns(
            "production-like",
            {
                "MRANKED_TEST_REVERSE_SYNC_POSTGRES_DSN": (
                    "postgresql://migration_bridge:do-not-leak@db/mranked"
                ),
                "MRANKED_TEST_REVERSE_SYNC_ADMIN_DSN": "host=db password = also-secret",
            },
        )
    assert "do-not-leak" not in str(captured.value)
    assert "also-secret" not in str(captured.value)


def _bridge_import(
    source_path: Path,
    *,
    dsn: str,
    namespace: str,
    snapshot_kind: str,
    report_dir: Path,
) -> tuple[Any, Mapping[str, Any]]:
    source = LegacySource(source_path)
    options = BridgeOptions(
        source=source_path,
        source_namespace=namespace,
        batch_size=2,
        report_dir=report_dir,
    )
    with PostgresTarget(dsn) as target:
        return BridgeService(
            options,
            source,
            target,
            snapshot_kind=snapshot_kind,
        ).run()


def _raw_batch(
    account: AccountRef,
    *,
    observed_at: datetime,
    ordinal: int,
) -> RawCollectionBatch:
    published_at = observed_at - timedelta(hours=2)
    discovered_at = published_at + timedelta(minutes=5)
    account_observation = RawAccountObservation(
        observed_at=observed_at,
        collected_at=observed_at,
        subscriber_count=20_000 + ordinal,
        subscriber_display=f"{20_000 + ordinal}",
        quality=ObservationQuality.EXACT,
        username=account.current_username,
        title=account.current_title,
        url=account.current_url,
        native_external_id=account.native_external_id,
        source={"gateway": "reverse-sync-postgres-integration"},
    )

    if account.platform == Platform.TELEGRAM:
        username = account.current_username or "reverse_sync_fixture"
        publication = RawPublication(
            external_id="g:987654321",
            published_at=published_at,
            discovered_at=discovered_at,
            observed_at=observed_at,
            collected_at=observed_at,
            publication_type="album",
            metrics={
                "views": 321,
                "reactions": 7,
                "comments": 0,
                "shares": None,
            },
            source={"gateway": "reverse-sync-postgres-integration"},
            public_url=f"https://t.me/{username}/8801",
            identities=(
                IdentityCandidate(
                    "m:8801",
                    IdentityRole.ALBUM_MEMBER,
                    public_url=f"https://t.me/{username}/8801",
                ),
                IdentityCandidate(
                    "m:8802",
                    IdentityRole.ALBUM_MEMBER,
                    public_url=f"https://t.me/{username}/8802",
                ),
            ),
            reaction_breakdown={"like": 5, "heart": 2},
            history_completeness=HistoryCompleteness.COMPLETE,
            is_repost=True,
            group_key="reverse-sync-postgres-album",
            quality_flags={"ambiguous_reactions": True},
        )
    elif account.platform == Platform.VK:
        publication = RawPublication(
            external_id="-100_987654",
            published_at=published_at,
            discovered_at=discovered_at,
            observed_at=observed_at,
            collected_at=observed_at,
            publication_type="post",
            metrics={
                "views": 1_500,
                "reactions": 51,
                "comments": 0,
                "shares": 3,
            },
            source={"gateway": "reverse-sync-postgres-integration"},
            public_url="https://vk.ru/wall-100_987654",
            source_external_id="77_987654",
            identities=(
                IdentityCandidate(
                    "77_987654",
                    IdentityRole.JOINT_AUTHOR,
                    public_url="https://vk.ru/wall77_987654",
                ),
            ),
            history_completeness=HistoryCompleteness.COMPLETE,
            quality_flags={
                "joint_post": True,
                "additional_author_count": 1,
            },
        )
    elif account.platform == Platform.MAX:
        publication = RawPublication(
            external_id="reverse-sync-max-987654",
            published_at=published_at,
            discovered_at=discovered_at,
            observed_at=observed_at,
            collected_at=observed_at,
            publication_type="post",
            metrics={
                "views": 0,
                "reactions": None,
                "comments": 0,
                "shares": 0,
            },
            source={"gateway": "reverse-sync-postgres-integration"},
            public_url="https://max.ru/beta_max/reverse-sync-max-987654",
            quality=ObservationQuality.ROUNDED,
            history_completeness=HistoryCompleteness.INCOMPLETE,
            is_repost=True,
            quality_flags={"engagement_request_degraded": True},
        )
    else:
        publication = RawPublication(
            external_id="reverse-sync-rutube-987654",
            published_at=published_at,
            discovered_at=discovered_at,
            observed_at=observed_at,
            collected_at=observed_at,
            publication_type="video",
            metrics={
                "views": 444,
                "reactions": 0,
                "comments": None,
                "shares": None,
            },
            source={"gateway": "reverse-sync-postgres-integration"},
            public_url="https://rutube.ru/video/reverse-sync-rutube-987654/",
            history_completeness=HistoryCompleteness.COMPLETE,
        )

    return RawCollectionBatch(
        account=account,
        account_observation=account_observation,
        publications=(publication,),
        source_name="reverse-sync-postgres-integration",
        source_version="1",
        cursor=(
            str(8_800 + ordinal)
            if account.platform == Platform.TELEGRAM
            else f"reverse-sync-{ordinal}"
        ),
    )


def _persist_batch(
    repository: PostgresCollectorRepository,
    account: AccountRef,
    *,
    observed_at: datetime,
    partition: str,
    ordinal: int,
) -> UUID:
    context = CollectionContext.create(
        account.platform,
        partition,
        "reverse-sync-postgres-integration-v1",
        observed_at,
        observed_at,
    )
    batch = CanonicalNormalizer().normalize(
        _raw_batch(account, observed_at=observed_at, ordinal=ordinal),
        context,
    )
    repository.start_run(context)
    assert repository.begin_account(context, account, context.started_at)
    result = repository.persist_account_batch(batch)
    assert result.revision_id is not None
    assert result.discovered_count == 1
    assert result.snapshot_count == 1
    assert repository.finish_run(context, observed_at).status.value == "succeeded"
    return batch.publications[0].id


def _target_identity_state(
    connection: Any,
    publication_ids: tuple[UUID, ...],
) -> dict[str, tuple[tuple[Any, ...], ...]]:
    publications = tuple(
        tuple(row.values())
        for row in connection.execute(
            """SELECT id::text, primary_account_id::text,
                      publication_type, published_at, discovered_at,
                      history_completeness::text, is_repost, quality_flags
                 FROM ingest.publication
                WHERE id=ANY(%s::uuid[])
                ORDER BY id""",
            (list(publication_ids),),
        ).fetchall()
    )
    identities = tuple(
        tuple(row.values())
        for row in connection.execute(
            """SELECT id, publication_id::text, external_id,
                      source_external_id, role::text, public_url
                 FROM ingest.publication_identity
                WHERE publication_id=ANY(%s::uuid[])
                ORDER BY publication_id, role, external_id""",
            (list(publication_ids),),
        ).fetchall()
    )
    snapshots = tuple(
        tuple(row.values())
        for row in connection.execute(
            """SELECT published_month, id, publication_id::text,
                      sampling_bucket, observed_at, collected_at, age_seconds,
                      views_count, reactions_count, comments_count, shares_count,
                      quality::text, interval_uncertain, synthetic,
                      metric_semantics_version, capability_version,
                      source_fingerprint, created_at
                 FROM ingest.publication_metric_snapshot
                WHERE publication_id=ANY(%s::uuid[])
                ORDER BY publication_id, sampling_bucket, id""",
            (list(publication_ids),),
        ).fetchall()
    )
    aliases = tuple(
        tuple(row.values())
        for row in connection.execute(
            """SELECT entity_type, legacy_id, target_uuid::text
                 FROM catalog.legacy_entity_alias
                WHERE target_uuid=ANY(%s::uuid[])
                  AND entity_type IN ('posts','platform_posts')
                ORDER BY entity_type, legacy_id""",
            (list(publication_ids),),
        ).fetchall()
    )
    return {
        "publications": publications,
        "identities": identities,
        "snapshots": snapshots,
        "aliases": aliases,
    }


def _duplicate_counts(
    connection: Any,
    publication_ids: tuple[UUID, ...],
) -> tuple[int, int, int, int]:
    row = connection.execute(
        """SELECT
               (SELECT count(*) FROM (
                    SELECT platform_account_id, observed_at, source_fingerprint
                      FROM ingest.account_metric_snapshot
                     WHERE platform_account_id IN (
                         SELECT primary_account_id
                           FROM ingest.publication
                          WHERE id=ANY(%s::uuid[])
                     )
                     GROUP BY platform_account_id, observed_at, source_fingerprint
                    HAVING count(*)>1
                ) AS duplicate_observation) AS observations,
               (SELECT count(*) FROM (
                    SELECT publication_id, external_id
                      FROM ingest.publication_identity
                     WHERE publication_id=ANY(%s::uuid[])
                     GROUP BY publication_id, external_id
                    HAVING count(*)>1
                ) AS duplicate_identity) AS identities,
               (SELECT count(*) FROM (
                    SELECT publication_id, role
                      FROM ingest.publication_identity
                     WHERE publication_id=ANY(%s::uuid[])
                       AND role='primary'
                     GROUP BY publication_id, role
                    HAVING count(*)<>1
                ) AS duplicate_primary) AS primary_identities,
               (SELECT count(*) FROM (
                    SELECT publication_id, sampling_bucket
                      FROM ingest.publication_metric_snapshot
                     WHERE publication_id=ANY(%s::uuid[])
                     GROUP BY publication_id, sampling_bucket
                    HAVING count(*)>1
                ) AS duplicate_snapshot) AS snapshots""",
        (
            list(publication_ids),
            list(publication_ids),
            list(publication_ids),
            list(publication_ids),
        ),
    ).fetchone()
    assert row is not None
    return (
        int(row["observations"]),
        int(row["identities"]),
        int(row["primary_identities"]),
        int(row["snapshots"]),
    )


def _legacy_counts(path: Path) -> tuple[int, int, int, int]:
    with sqlite3.connect(path) as connection:
        return tuple(
            int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            for table in (
                "posts",
                "platform_posts",
                "reaction_snapshots",
                "platform_snapshots",
            )
        )


@pytest.mark.skipif(
    not POSTGRES_DSN,
    reason=(
        "set MRANKED_TEST_REVERSE_SYNC_POSTGRES_DSN to an empty disposable "
        "Flyway-V8 PostgreSQL database"
    ),
)
def test_postgres_reverse_sync_round_trip_preserves_target_identity(
    tmp_path: Path,
) -> None:
    """Exercise Writer Gate W against a caller-provisioned disposable database.

    The test deliberately neither creates nor drops the database. The dedicated
    database must contain only a successful Flyway V1-V8 migration before this
    test starts, because reverse sync fixes a database-wide revision set.
    """

    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    reverse_dsn = str(POSTGRES_DSN).strip()
    bridge_dsn = _dsn("MRANKED_TEST_REVERSE_SYNC_BRIDGE_DSN", reverse_dsn)
    collector_dsn = _dsn("MRANKED_TEST_REVERSE_SYNC_COLLECTOR_DSN", reverse_dsn)
    admin_dsn = _dsn("MRANKED_TEST_REVERSE_SYNC_ADMIN_DSN", reverse_dsn)
    local_namespace = f"pytest-reverse-sync-{uuid4()}"
    rehearsal_context = _rehearsal_context(local_namespace)
    _require_password_free_production_dsns(
        rehearsal_context["environment"],
        {
            "MRANKED_TEST_REVERSE_SYNC_POSTGRES_DSN": reverse_dsn,
            "MRANKED_TEST_REVERSE_SYNC_BRIDGE_DSN": bridge_dsn,
            "MRANKED_TEST_REVERSE_SYNC_COLLECTOR_DSN": collector_dsn,
            "MRANKED_TEST_REVERSE_SYNC_ADMIN_DSN": admin_dsn,
        },
    )
    namespace = rehearsal_context["sourceNamespace"]
    file_sha256_manifest = {
        script: hashlib.sha256((MIGRATION_DIR / script).read_bytes()).hexdigest()
        for _version, script, _sha256, _checksum in EXPECTED_FLYWAY_MIGRATIONS
    }
    assert file_sha256_manifest == {
        script: sha256
        for _version, script, sha256, _checksum in EXPECTED_FLYWAY_MIGRATIONS
    }

    def connect(dsn: str) -> Any:
        return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

    with connect(admin_dsn) as admin:
        flyway_rows = admin.execute(
            """SELECT installed_rank, version, description, type,
                      script, checksum, success
                 FROM flyway.flyway_schema_history
                ORDER BY installed_rank"""
        ).fetchall()
        flyway_manifest = _validated_flyway_manifest(flyway_rows)
        expected_database_manifest = [
            {
                "version": version,
                "script": script,
                "checksum": checksum,
                "success": True,
            }
            for version, script, _sha256, checksum in EXPECTED_FLYWAY_MIGRATIONS
        ]
        assert flyway_manifest == expected_database_manifest, (
            "reverse-sync PostgreSQL integration requires exactly successful "
            "Flyway V1-V8 version/script/checksum history"
        )
        database_row = admin.execute(
            "SELECT current_database() AS database_name"
        ).fetchone()
        assert database_row is not None
        database_name = str(database_row["database_name"])
        existing = admin.execute(
            """SELECT
                   (SELECT count(*) FROM migration.import_batch) AS batches,
                   (SELECT count(*) FROM analytics.dataset_revision) AS revisions,
                   (SELECT count(*) FROM catalog.platform_account) AS accounts,
                   (SELECT count(*) FROM catalog.legacy_entity_alias) AS aliases"""
        ).fetchone()
        assert existing == {
            "batches": 0,
            "revisions": 0,
            "accounts": 0,
            "aliases": 0,
        }, "MRANKED_TEST_REVERSE_SYNC_POSTGRES_DSN must point to an empty database"

    source_fixture = tmp_path / "s-final-source.sqlite"
    legacy_target = tmp_path / "legacy-reverse-target.sqlite"
    build_golden_fixture(source_fixture, revision=1)
    create_online_backup(source_fixture, legacy_target)
    with sqlite3.connect(legacy_target) as legacy:
        assert legacy.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"

    s_final_stats, s_final_report = _bridge_import(
        source_fixture,
        dsn=bridge_dsn,
        namespace=namespace,
        snapshot_kind="s_final",
        report_dir=tmp_path / "s-final-report",
    )
    assert s_final_report["gate"] == {
        "status": "pass",
        "critical_mismatches": 0,
    }, s_final_report["mismatches"]
    assert s_final_stats.rows_written > 0

    from operations.reverse_sync.journal import ReverseSyncJournal
    from operations.reverse_sync.postgres import PostgresReverseSource
    from operations.reverse_sync.service import ReverseSyncService
    from operations.reverse_sync.sqlite_target import LegacySqliteTarget

    source = PostgresReverseSource(reverse_dsn, namespace)
    target = LegacySqliteTarget(legacy_target, namespace, min_free_bytes=0)
    journal = ReverseSyncJournal(tmp_path / "reverse-sync-journal.sqlite")
    service = ReverseSyncService(source, target, journal)

    preflight = service.preflight()
    assert preflight["status"] == "pass"
    assert preflight["postgres"]["sFinalBatchId"] == str(s_final_stats.batch_id)
    started = service.start(
        rollback_window_hours=24,
        operator=rehearsal_context["operator"],
        ticket=rehearsal_context["changeTicket"],
    )
    assert started["status"] == "active"
    assert started["baselineRevisionCount"] > 0

    repository = PostgresCollectorRepository(collector_dsn)
    accounts: dict[Platform, AccountRef] = {}
    for platform in Platform:
        loaded = tuple(repository.enabled_accounts(platform, "all"))
        assert len(loaded) == 1
        accounts[platform] = loaded[0]

    partition = f"reverse-sync-{uuid4()}"
    observed_base = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(
        seconds=2
    )
    publication_ids: dict[Platform, UUID] = {}
    for ordinal, platform in enumerate((Platform.TELEGRAM, Platform.VK), start=1):
        publication_ids[platform] = _persist_batch(
            repository,
            accounts[platform],
            observed_at=observed_base + timedelta(minutes=ordinal),
            partition=partition,
            ordinal=ordinal,
        )

    first_apply = service.once()
    assert first_apply["status"] == "active"
    assert first_apply["revisionCount"] == 2
    assert first_apply["caughtUp"] is True
    first_legacy_counts = _legacy_counts(legacy_target)

    replay = service.once()
    assert replay["planSha256"] == first_apply["planSha256"]
    assert replay["revisionSetSha256"] == first_apply["revisionSetSha256"]
    assert replay["caughtUp"] is True
    assert _legacy_counts(legacy_target) == first_legacy_counts

    for ordinal, platform in enumerate((Platform.MAX, Platform.RUTUBE), start=3):
        publication_ids[platform] = _persist_batch(
            repository,
            accounts[platform],
            observed_at=observed_base + timedelta(minutes=ordinal),
            partition=partition,
            ordinal=ordinal,
        )

    drained = service.drain(
        operator=rehearsal_context["operator"],
        ticket=rehearsal_context["changeTicket"],
    )
    assert drained["status"] == "drained"
    assert drained["fixedRevisionCount"] == 4
    drained_counts = _legacy_counts(legacy_target)
    assert tuple(after - before for before, after in zip(
        first_legacy_counts, drained_counts, strict=True
    )) == (0, 2, 0, 2)

    repeated_drain = service.drain(
        operator=rehearsal_context["operator"],
        ticket=rehearsal_context["changeTicket"],
    )
    assert repeated_drain["idempotent"] is True
    assert repeated_drain["planSha256"] == drained["planSha256"]
    assert _legacy_counts(legacy_target) == drained_counts

    verified = service.verify()
    assert verified["status"] == "verified"
    assert verified["planSha256"] == drained["planSha256"]
    repeated_verify = service.verify()
    assert repeated_verify["idempotent"] is True
    stopped = service.stop()
    assert stopped["status"] == "stopped"
    assert service.stop()["idempotent"] is True

    ordered_publication_ids = tuple(
        publication_ids[platform] for platform in Platform
    )
    with connect(admin_dsn) as admin:
        before_round_trip = _target_identity_state(admin, ordered_publication_ids)
        assert len(before_round_trip["publications"]) == 4
        assert len(before_round_trip["snapshots"]) == 4
        assert len(before_round_trip["aliases"]) == 4
        assert len(before_round_trip["identities"]) == 7
        assert sum(
            identity[4] == "primary"
            for identity in before_round_trip["identities"]
        ) == 4
        assert {alias[0] for alias in before_round_trip["aliases"]} == {
            "posts",
            "platform_posts",
        }
        assert _duplicate_counts(admin, ordered_publication_ids) == (0, 0, 0, 0)

    reverse_export = tmp_path / "legacy-reverse-export.sqlite"
    create_online_backup(legacy_target, reverse_export)
    forward_stats, forward_report = _bridge_import(
        reverse_export,
        dsn=bridge_dsn,
        namespace=namespace,
        snapshot_kind="catch_up",
        report_dir=tmp_path / "forward-report",
    )
    assert forward_report["gate"] == {
        "status": "pass",
        "critical_mismatches": 0,
    }, forward_report["mismatches"]
    assert forward_stats.rows_written > 0

    with connect(admin_dsn) as admin:
        after_round_trip = _target_identity_state(admin, ordered_publication_ids)
        duplicate_counts = _duplicate_counts(admin, ordered_publication_ids)
        assert duplicate_counts == (0, 0, 0, 0)
    preservation_mismatches = {
        "publicationMismatches": int(
            after_round_trip["publications"] != before_round_trip["publications"]
        ),
        "identityMismatches": int(
            after_round_trip["identities"] != before_round_trip["identities"]
        ),
        "snapshotMismatches": int(
            after_round_trip["snapshots"] != before_round_trip["snapshots"]
        ),
        "aliasMismatches": int(
            after_round_trip["aliases"] != before_round_trip["aliases"]
        ),
    }
    assert set(preservation_mismatches.values()) == {0}

    repeat_stats, repeat_report = _bridge_import(
        reverse_export,
        dsn=bridge_dsn,
        namespace=namespace,
        snapshot_kind="catch_up",
        report_dir=tmp_path / "forward-repeat-report",
    )
    assert repeat_report["gate"]["status"] == "pass"
    assert repeat_stats.batch_id == forward_stats.batch_id
    assert repeat_stats.rows_written == 0
    with connect(admin_dsn) as admin:
        assert _target_identity_state(admin, ordered_publication_ids) == before_round_trip

    journal_integrity = journal.integrity()
    assert journal_integrity["schemaVersion"] == 3
    s_final_source_sha256 = str(s_final_report["source"]["source_sha256"])
    assert preflight["postgres"]["sFinalSourceSha256"] == s_final_source_sha256
    assert stopped["sFinalBatchId"] == str(s_final_stats.batch_id)
    assert stopped["sFinalSourceSha256"] == s_final_source_sha256
    assert stopped["sourceNamespace"] == namespace
    assert stopped["operator"] == rehearsal_context["operator"]
    assert stopped["ticket"] == rehearsal_context["changeTicket"]
    assert stopped["planSha256"] == drained["planSha256"]

    _write_rehearsal_evidence(
        {
            "reportType": "reverse-sync-rehearsal",
            "reportVersion": 3,
            "status": "pass",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "environment": rehearsal_context["environment"],
            "release": {
                "id": rehearsal_context["releaseId"],
                "sha256SumsSha256": rehearsal_context[
                    "releaseManifestSha256"
                ],
            },
            "operator": rehearsal_context["operator"],
            "changeTicket": rehearsal_context["changeTicket"],
            "sourceNamespace": namespace,
            "database": database_name,
            "flyway": {
                "schemaVersion": 8,
                "migrationCount": len(flyway_manifest),
                "fileSha256": file_sha256_manifest,
                "databaseMigrations": flyway_manifest,
            },
            "platforms": sorted(platform.value for platform in Platform),
            "replay": {
                "runCount": 4,
                "idempotent": True,
            },
            "duplicates": {
                "observationCount": duplicate_counts[0],
                "identityCount": duplicate_counts[1],
                "primaryIdentityCount": duplicate_counts[2],
                "snapshotCount": duplicate_counts[3],
            },
            "preservation": preservation_mismatches,
            "forwardReconciliation": {
                "status": forward_report["gate"]["status"],
                "criticalMismatches": forward_report["gate"][
                    "critical_mismatches"
                ],
            },
            "reverseSync": {
                "status": stopped["status"],
                "journalStateVersion": journal_integrity["schemaVersion"],
                "baselineRevisionCount": started["baselineRevisionCount"],
                "baselineRevisionSetSha256": started[
                    "baselineRevisionSetSha256"
                ],
                "fixedRevisionCount": drained["fixedRevisionCount"],
                "fixedRevisionSetSha256": drained[
                    "fixedRevisionSetSha256"
                ],
                "planSha256": stopped["planSha256"],
            },
            "sFinal": {
                "batchId": str(s_final_stats.batch_id),
                "sourceSha256": s_final_source_sha256,
                "gate": s_final_report["gate"]["status"],
            },
        }
    )
