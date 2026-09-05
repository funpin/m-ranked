from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from typing import Any, Callable
from uuid import uuid4

import pytest

import operations.collector_parity_evidence as evidence_module
from operations.collector_parity_evidence import (
    AUTHORITATIVE_MISSING_REASONS,
    EXPECTED_MIGRATIONS,
    EXPECTED_POLICY,
    PROVIDER_MODES,
    EvidenceError,
    main,
    seal_report,
    verify_report,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = ROOT / "backend/src/main/resources/db/migration"
OPERATOR = "operator-alice"
DEPLOY_TICKET = "DEPLOY-2042"
APPROVAL_TICKET = "COLLECTOR-PARITY-2042"
SOURCE_NAMESPACE = "m-ranked-production"


def _utc(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, Any], mode: int = 0o600) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(mode)


def _write_sidecar(path: Path, *, basename_only: bool = False) -> None:
    named_path = path.name if basename_only else str(path)
    sidecar = Path(f"{path}.sha256")
    sidecar.write_text(f"{_sha256(path)}  {named_path}\n", encoding="ascii")
    sidecar.chmod(0o600)


def _refresh_deploy_report(workspace: dict[str, Any]) -> None:
    path = workspace["deploy_report"]
    report = json.loads(path.read_text(encoding="utf-8"))
    report["releaseManifestSha256"] = _sha256(workspace["release"] / "SHA256SUMS")
    _write_json(path, report)
    _write_sidecar(path)


def _refresh_release_manifest_entry(
    workspace: dict[str, Any], relative_name: str
) -> None:
    release = workspace["release"]
    manifest = release / "SHA256SUMS"
    replacement = f"{_sha256(release / relative_name)}  {relative_name}"
    lines = manifest.read_text(encoding="ascii").splitlines()
    matches = [index for index, line in enumerate(lines) if line.endswith(f"  {relative_name}")]
    assert len(matches) == 1
    lines[matches[0]] = replacement
    manifest.write_text("\n".join(lines) + "\n", encoding="ascii")
    _refresh_deploy_report(workspace)


def _raw_file(root: Path, name: str, now: datetime) -> dict[str, Any]:
    path = root / name
    payload = f"sanitized live shadow evidence for {name}\n".encode()
    path.write_bytes(payload)
    timestamp = (now - timedelta(minutes=2)).timestamp()
    os.utime(path, (timestamp, timestamp))
    path.chmod(0o400)
    return {"bytes": len(payload), "path": str(path), "sha256": _sha256(path)}


def _database_migrations() -> list[dict[str, Any]]:
    return [
        {
            "checksum": checksum,
            "script": filename,
            "success": True,
            "version": version,
        }
        for version, filename, _sha256sum, checksum in EXPECTED_MIGRATIONS
    ]


def _platform(
    name: str,
    raw: dict[str, Any],
    started_at: datetime,
    finished_at: datetime,
    revision: int,
) -> dict[str, Any]:
    run_ids = [str(uuid4()) for _ in range(4)]
    reason = sorted(AUTHORITATIVE_MISSING_REASONS[name])[0]
    mode = sorted(PROVIDER_MODES[name])[0]
    return {
        "accountIds": [str(uuid4())],
        "authoritativeMissingReason": reason,
        "deletionLifecycle": {
            "confirmedAfterChecks": 2,
            "confirmedRunId": run_ids[1],
            "controlledPublication": True,
            "deletedAtCleared": True,
            "firstMissingRunId": run_ids[0],
            "historicalRowCountAfterRediscovery": 9,
            "historicalRowCountBefore": 7,
            "identityRowsPreserved": True,
            "publicationRowPreserved": True,
            "rediscoveredRunId": run_ids[2],
            "secondMissingRunId": run_ids[1],
            "stateAfterRediscovery": "present",
        },
        "discovery": {
            "cursorWrapCount": 1,
            "cycleCount": 5,
            "discoveryPagePublicationCount": 100,
            "exactLookupRefreshCount": 1,
            "trackedPublicationCount": 101,
        },
        "finishedAt": _utc(finished_at),
        "latestRevision": revision,
        "platform": name,
        "providerMode": mode,
        "rawEvidence": raw,
        "replay": {
            "attemptCount": 2,
            "newDatasetRevisionCount": 0,
            "newDeletionObservationCount": 0,
            "newOutboxEventCount": 0,
            "newSnapshotCount": 0,
            "runId": run_ids[3],
        },
        "runIds": run_ids,
        "startedAt": _utc(started_at),
        "transientFailures": {
            name: {"attemptCount": 1, "missingCounterIncrements": 0}
            for name in (
                "ambiguousDiscovery",
                "authentication",
                "rateLimit",
                "transport",
            )
        },
    }


@pytest.fixture
def evidence_workspace(tmp_path: Path) -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    install_root = tmp_path / "releases"
    release = install_root / "release-2042"
    migration_root = release / "backend/src/main/resources/db/migration"
    migration_root.mkdir(parents=True)
    symlink_manifest = release / "SYMLINKS.sha256"
    symlink_manifest.write_bytes(b"")
    manifest_lines: list[str] = [
        f"{_sha256(symlink_manifest)}  SYMLINKS.sha256"
    ]
    for _version, filename, sha256sum, _checksum in EXPECTED_MIGRATIONS:
        target = migration_root / filename
        target.write_bytes((MIGRATION_DIR / filename).read_bytes())
        assert _sha256(target) == sha256sum
        relative = target.relative_to(release).as_posix()
        manifest_lines.append(f"{sha256sum}  {relative}")
    manifest = release / "SHA256SUMS"
    manifest.write_text("\n".join(manifest_lines) + "\n", encoding="ascii")

    active_link = tmp_path / "current"
    active_link.symlink_to(release, target_is_directory=True)
    deploy_report = tmp_path / "deploy-current.json"
    deploy = {
        "changeTicket": DEPLOY_TICKET,
        "finishedAt": _utc(now - timedelta(hours=2)),
        "flyway": {
            "engineVersion": "12.0.0",
            "migrationCount": 8,
            "schemaVersion": "8",
            "validated": True,
            **{
                f"v{version}Sha256": sha256sum
                for version, _filename, sha256sum, _checksum in EXPECTED_MIGRATIONS
            },
        },
        "legacyUnitsChanged": False,
        "operator": "release-engineer-bob",
        "projectionPublisherActive": True,
        "publicRoutingChanged": False,
        "releaseId": release.name,
        "releaseManifestSha256": _sha256(manifest),
        "releasePath": str(release),
        "status": "pass",
    }
    _write_json(deploy_report, deploy)
    _write_sidecar(deploy_report)

    evidence_root = tmp_path / "shadow-evidence"
    evidence_root.mkdir()
    started_at = now - timedelta(hours=1)
    finished_at = now - timedelta(minutes=1)
    raw_database = _raw_file(evidence_root, "database.txt", now)
    platforms = [
        _platform(
            platform,
            _raw_file(evidence_root, f"{platform}.txt", now),
            started_at + timedelta(minutes=1),
            finished_at - timedelta(seconds=1),
            101 + index,
        )
        for index, platform in enumerate(("telegram", "vk", "max", "rutube"))
    ]
    source = {
        "approvalTicket": APPROVAL_TICKET,
        "attestation": {
            "controlledProviderResources": True,
            "evidenceOrigin": "live-provider-shadow",
            "fixtureBacked": False,
            "isolatedTargetCredentials": True,
            "legacyCollectorConcurrent": True,
            "legacyUnitsChanged": False,
            "liveProviderInteractions": True,
            "productionTrafficMutated": False,
            "routesChanged": False,
            "unitTestBacked": False,
        },
        "database": {
            "name": "mranked_shadow_20260905",
            "rawEvidence": raw_database,
        },
        "duplicates": {
            "accountExternalIdentity": 0,
            "accountIdentityHistory": 0,
            "datasetRevision": 0,
            "deletionObservation": 0,
            "outboxEvent": 0,
            "publication": 0,
            "publicationMetricSnapshot": 0,
        },
        "environment": "production-like",
        "evidenceType": "collector-parity-shadow-observations",
        "evidenceVersion": 1,
        "finishedAt": _utc(finished_at),
        "flywayDatabaseMigrations": _database_migrations(),
        "operator": OPERATOR,
        "platforms": platforms,
        "policy": dict(EXPECTED_POLICY),
        "projection": {
            "latestCollectorRevision": 104,
            "latestDatasetRevision": 104,
            "states": {
                "comparison": {"revision": 104, "status": "ready"},
                "institution_daily_metrics": {"revision": 104, "status": "ready"},
                "institution_monthly_metrics": {"revision": 104, "status": "ready"},
                "institution_period_metrics": {"revision": 104, "status": "ready"},
                "publication_hourly": {"revision": 104, "status": "ready"},
                "publication_latest": {"revision": 104, "status": "ready"},
            },
        },
        "sourceNamespace": SOURCE_NAMESPACE,
        "startedAt": _utc(started_at),
        "status": "pass",
    }
    return {
        "active_link": active_link,
        "deploy_report": deploy_report,
        "evidence_root": evidence_root,
        "install_root": install_root,
        "now": now,
        "release": release,
        "source": source,
    }


def _common(workspace: dict[str, Any]) -> dict[str, Any]:
    return {
        "active_release_link": workspace["active_link"],
        "approval_ticket": APPROVAL_TICKET,
        "deploy_report_path": workspace["deploy_report"],
        "evidence_root": workspace["evidence_root"],
        "install_root": workspace["install_root"],
        "max_age_seconds": 86_400,
        "now": workspace["now"],
        "operator": OPERATOR,
        "source_namespace": SOURCE_NAMESPACE,
    }


def test_seal_and_verify_strict_live_shadow_report(
    evidence_workspace: dict[str, Any],
) -> None:
    output = evidence_workspace["evidence_root"] / "collector-parity.json"
    report = seal_report(
        evidence_workspace["source"], output_path=output, **_common(evidence_workspace)
    )

    assert report["reportType"] == "collector-parity-rehearsal"
    assert report["reportVersion"] == 1
    assert report["release"] == {
        "deployFinishedAt": _utc(evidence_workspace["now"] - timedelta(hours=2)),
        "deployReportSha256": _sha256(evidence_workspace["deploy_report"]),
        "deployTicket": DEPLOY_TICKET,
        "id": "release-2042",
        "sha256SumsSha256": _sha256(evidence_workspace["release"] / "SHA256SUMS"),
    }
    assert report["flyway"]["databaseMigrations"] == _database_migrations()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert stat.S_IMODE(Path(f"{output}.sha256").stat().st_mode) == 0o600
    assert Path(f"{output}.sha256").read_text(encoding="ascii") == (
        f"{_sha256(output)}  {output.name}\n"
    )

    verified = verify_report(output, **_common(evidence_workspace))
    assert verified == report


def test_legacy_four_boolean_report_is_not_gate_evidence(
    evidence_workspace: dict[str, Any],
) -> None:
    legacy = evidence_workspace["evidence_root"] / "legacy-four-booleans.json"
    _write_json(
        legacy,
        {
            "status": "pass",
            "checks": {
                "fourPlatforms": True,
                "historicalRefresh": True,
                "confirmedDeletion": True,
                "idempotentResume": True,
            },
        },
    )
    _write_sidecar(legacy, basename_only=True)

    with pytest.raises(EvidenceError):
        verify_report(legacy, **_common(evidence_workspace))


def _fixture_backed(source: dict[str, Any]) -> None:
    source["attestation"]["fixtureBacked"] = True


def _unit_backed(source: dict[str, Any]) -> None:
    source["attestation"]["unitTestBacked"] = True


def _wrong_environment(source: dict[str, Any]) -> None:
    source["environment"] = "local"


def _unsafe_policy(source: dict[str, Any]) -> None:
    source["policy"]["deletionConfirmationChecks"] = 1


def _stale_projection(source: dict[str, Any]) -> None:
    source["projection"]["states"]["comparison"]["revision"] = 103


def _duplicate_snapshot(source: dict[str, Any]) -> None:
    source["duplicates"]["publicationMetricSnapshot"] = 1


def _unknown_platform(source: dict[str, Any]) -> None:
    source["platforms"][0]["platform"] = "youtube"


def _feed_omission(source: dict[str, Any]) -> None:
    source["platforms"][0]["authoritativeMissingReason"] = "feed_omission"


def _float_zero(source: dict[str, Any]) -> None:
    source["duplicates"]["publicationMetricSnapshot"] = 0.0


def _float_policy(source: dict[str, Any]) -> None:
    source["policy"]["refreshLimit"] = 100.0


def _float_revision(source: dict[str, Any]) -> None:
    source["projection"]["states"]["comparison"]["revision"] = 104.0


def _float_source_version(source: dict[str, Any]) -> None:
    source["evidenceVersion"] = 1.0


def _float_flyway_checksum(source: dict[str, Any]) -> None:
    source["flywayDatabaseMigrations"][0]["checksum"] = float(
        source["flywayDatabaseMigrations"][0]["checksum"]
    )


def _numeric_flyway_success(source: dict[str, Any]) -> None:
    source["flywayDatabaseMigrations"][0]["success"] = 1


@pytest.mark.parametrize(
    "mutate",
    (
        _fixture_backed,
        _unit_backed,
        _wrong_environment,
        _unsafe_policy,
        _stale_projection,
        _duplicate_snapshot,
        _unknown_platform,
        _feed_omission,
        _float_zero,
        _float_policy,
        _float_revision,
        _float_source_version,
        _float_flyway_checksum,
        _numeric_flyway_success,
    ),
)
def test_sealer_rejects_non_shadow_or_incomplete_claims(
    evidence_workspace: dict[str, Any], mutate: Callable[[dict[str, Any]], None]
) -> None:
    source = deepcopy(evidence_workspace["source"])
    mutate(source)

    with pytest.raises(EvidenceError):
        seal_report(
            source,
            output_path=evidence_workspace["evidence_root"] / "rejected.json",
            **_common(evidence_workspace),
        )


def test_sealer_rejects_mutable_or_reused_raw_evidence(
    evidence_workspace: dict[str, Any],
) -> None:
    source = deepcopy(evidence_workspace["source"])
    raw_path = Path(source["platforms"][0]["rawEvidence"]["path"])
    raw_path.chmod(0o600)
    with pytest.raises(EvidenceError, match="immutable"):
        seal_report(
            source,
            output_path=evidence_workspace["evidence_root"] / "mutable.json",
            **_common(evidence_workspace),
        )

    raw_path.chmod(0o400)
    source = deepcopy(evidence_workspace["source"])
    source["platforms"][1]["rawEvidence"] = deepcopy(
        source["platforms"][0]["rawEvidence"]
    )
    with pytest.raises(EvidenceError, match="distinct"):
        seal_report(
            source,
            output_path=evidence_workspace["evidence_root"] / "reused.json",
            **_common(evidence_workspace),
        )


def test_release_binding_is_derived_and_revalidated(
    evidence_workspace: dict[str, Any],
) -> None:
    migration = (
        evidence_workspace["release"]
        / "backend/src/main/resources/db/migration/V8__legacy_overview_projection.sql"
    )
    migration.write_bytes(migration.read_bytes() + b"\n-- tampered\n")

    with pytest.raises(EvidenceError, match="manifest mismatch"):
        seal_report(
            evidence_workspace["source"],
            output_path=evidence_workspace["evidence_root"] / "unbound.json",
            **_common(evidence_workspace),
        )


def test_release_binding_rejects_intermediate_alias_target(
    evidence_workspace: dict[str, Any],
) -> None:
    release_alias = evidence_workspace["install_root"].parent / "release-alias"
    release_alias.symlink_to(evidence_workspace["release"], target_is_directory=True)
    active_link = evidence_workspace["active_link"]
    active_link.unlink()
    active_link.symlink_to(release_alias, target_is_directory=True)

    with pytest.raises(EvidenceError, match="raw target must equal"):
        seal_report(
            evidence_workspace["source"],
            output_path=evidence_workspace["evidence_root"] / "aliased-release.json",
            **_common(evidence_workspace),
        )


def test_release_manifest_requires_exact_whole_regular_tree(
    evidence_workspace: dict[str, Any],
) -> None:
    extra = evidence_workspace["release"] / "unlisted-runtime.py"
    extra.write_text("raise SystemExit('unlisted')\n", encoding="utf-8")

    with pytest.raises(EvidenceError, match="exactly every regular file"):
        seal_report(
            evidence_workspace["source"],
            output_path=evidence_workspace["evidence_root"] / "unlisted.json",
            **_common(evidence_workspace),
        )


def test_release_inventory_fails_closed_on_unreadable_subtree(
    evidence_workspace: dict[str, Any],
) -> None:
    hidden = evidence_workspace["release"] / "execute-only"
    hidden.mkdir()
    (hidden / "unlisted.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    hidden.chmod(0o100)
    try:
        with pytest.raises(EvidenceError, match="inventoried completely"):
            seal_report(
                evidence_workspace["source"],
                output_path=evidence_workspace["evidence_root"] / "unreadable.json",
                **_common(evidence_workspace),
            )
    finally:
        hidden.chmod(0o700)


def test_release_tree_budget_is_checked_before_manifest_entry_hashing(
    evidence_workspace: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original_reader = evidence_module._read_stable_file
    hashed_manifest_entries: list[Path] = []

    def observed_reader(
        path: Path, label: str, **kwargs: Any
    ) -> evidence_module.FileSnapshot:
        if label.startswith("manifest entry "):
            hashed_manifest_entries.append(path)
        return original_reader(path, label, **kwargs)

    monkeypatch.setattr(evidence_module, "MAX_RELEASE_TREE_BYTES", 0)
    monkeypatch.setattr(evidence_module, "_read_stable_file", observed_reader)

    with pytest.raises(EvidenceError, match="inventory exceeds the size budget"):
        seal_report(
            evidence_workspace["source"],
            output_path=evidence_workspace["evidence_root"] / "oversized-release.json",
            **_common(evidence_workspace),
        )

    assert hashed_manifest_entries == []


def test_symlink_manifest_accepts_bound_internal_link_and_rejects_unlisted_link(
    evidence_workspace: dict[str, Any],
) -> None:
    release = evidence_workspace["release"]
    relative_link = "frontend/node_modules/migration-reference"
    link = release / relative_link
    link.parent.mkdir(parents=True)
    raw_target = "../../backend/src/main/resources/db/migration/V1__target_baseline.sql"
    link.symlink_to(raw_target)
    symlink_manifest = release / "SYMLINKS.sha256"
    symlink_manifest.write_text(
        f"{hashlib.sha256(raw_target.encode('ascii')).hexdigest()}  {relative_link}\n",
        encoding="ascii",
    )
    _refresh_release_manifest_entry(evidence_workspace, "SYMLINKS.sha256")

    output = evidence_workspace["evidence_root"] / "internal-link.json"
    seal_report(
        evidence_workspace["source"], output_path=output, **_common(evidence_workspace)
    )
    assert output.exists()

    extra_link = release / "frontend/node_modules/unlisted-link"
    extra_link.symlink_to(raw_target)
    with pytest.raises(EvidenceError, match="exactly every symlink"):
        verify_report(output, **_common(evidence_workspace))


def test_symlink_manifest_rejects_absolute_internal_target(
    evidence_workspace: dict[str, Any],
) -> None:
    release = evidence_workspace["release"]
    relative_link = "absolute-internal-link"
    target = (
        release
        / "backend/src/main/resources/db/migration/V1__target_baseline.sql"
    )
    raw_target = str(target)
    (release / relative_link).symlink_to(raw_target)
    symlink_manifest = release / "SYMLINKS.sha256"
    symlink_manifest.write_text(
        f"{hashlib.sha256(raw_target.encode('ascii')).hexdigest()}  {relative_link}\n",
        encoding="ascii",
    )
    _refresh_release_manifest_entry(evidence_workspace, "SYMLINKS.sha256")

    with pytest.raises(EvidenceError, match="internal symlink target must be relative"):
        seal_report(
            evidence_workspace["source"],
            output_path=evidence_workspace["evidence_root"] / "absolute-internal.json",
            **_common(evidence_workspace),
        )


def test_symlink_manifest_rejects_external_alias_returning_inside(
    evidence_workspace: dict[str, Any],
) -> None:
    release = evidence_workspace["release"]
    target = (
        release
        / "backend/src/main/resources/db/migration/V1__target_baseline.sql"
    )
    returning_alias = release.parent.parent / "outside-alias-returning-inside"
    returning_alias.symlink_to(target)
    relative_link = "returning-link"
    link = release / relative_link
    raw_target = os.path.relpath(returning_alias, link.parent)
    link.symlink_to(raw_target)
    symlink_manifest = release / "SYMLINKS.sha256"
    symlink_manifest.write_text(
        f"{hashlib.sha256(raw_target.encode('ascii')).hexdigest()}  {relative_link}\n",
        encoding="ascii",
    )
    _refresh_release_manifest_entry(evidence_workspace, "SYMLINKS.sha256")

    with pytest.raises(EvidenceError, match="first-hop parent escapes its tree"):
        seal_report(
            evidence_workspace["source"],
            output_path=evidence_workspace["evidence_root"] / "returning-alias.json",
            **_common(evidence_workspace),
        )


@pytest.mark.parametrize("filename", ("V9__unapproved.sql", "R__repeatable.sql"))
def test_release_manifest_rejects_v9_and_repeatable_migrations(
    evidence_workspace: dict[str, Any], filename: str
) -> None:
    migration = (
        evidence_workspace["release"]
        / "backend/src/main/resources/db/migration"
        / filename
    )
    migration.write_text("SELECT 1;\n", encoding="utf-8")
    manifest = evidence_workspace["release"] / "SHA256SUMS"
    with manifest.open("a", encoding="ascii") as stream:
        stream.write(
            f"{_sha256(migration)}  {migration.relative_to(evidence_workspace['release']).as_posix()}\n"
        )
    _refresh_deploy_report(evidence_workspace)

    with pytest.raises(EvidenceError, match="exactly regular V1-V8"):
        seal_report(
            evidence_workspace["source"],
            output_path=evidence_workspace["evidence_root"] / "extra-migration.json",
            **_common(evidence_workspace),
        )


def test_source_namespace_is_identifier_only(
    evidence_workspace: dict[str, Any],
) -> None:
    source = deepcopy(evidence_workspace["source"])
    source["sourceNamespace"] = "https://collector.example/source"
    common = _common(evidence_workspace)
    common["source_namespace"] = source["sourceNamespace"]

    with pytest.raises(EvidenceError, match="namespace"):
        seal_report(
            source,
            output_path=evidence_workspace["evidence_root"] / "uri-namespace.json",
            **common,
        )


def test_raw_evidence_rejects_hardlinks_and_out_of_window_mtime(
    evidence_workspace: dict[str, Any],
) -> None:
    source = deepcopy(evidence_workspace["source"])
    original = Path(source["platforms"][0]["rawEvidence"]["path"])
    hardlink = evidence_workspace["evidence_root"] / "telegram-hardlink.txt"
    os.link(original, hardlink)
    with pytest.raises(EvidenceError, match="hardlink"):
        seal_report(
            source,
            output_path=evidence_workspace["evidence_root"] / "hardlink.json",
            **_common(evidence_workspace),
        )

    hardlink.unlink()
    too_early = datetime.strptime(
        source["platforms"][0]["startedAt"], "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=timezone.utc) - timedelta(minutes=1)
    os.utime(original, (too_early.timestamp(), too_early.timestamp()))
    with pytest.raises(EvidenceError, match="capture window"):
        seal_report(
            source,
            output_path=evidence_workspace["evidence_root"] / "bad-mtime.json",
            **_common(evidence_workspace),
        )


def test_deployment_must_precede_rehearsal_and_is_sealed_into_provenance(
    evidence_workspace: dict[str, Any],
) -> None:
    deploy_path = evidence_workspace["deploy_report"]
    deploy = json.loads(deploy_path.read_text(encoding="utf-8"))
    deploy["finishedAt"] = evidence_workspace["source"]["startedAt"]
    _write_json(deploy_path, deploy)
    _write_sidecar(deploy_path)

    with pytest.raises(EvidenceError, match="start after"):
        seal_report(
            evidence_workspace["source"],
            output_path=evidence_workspace["evidence_root"] / "deploy-after.json",
            **_common(evidence_workspace),
        )


def test_active_release_link_swap_is_detected(
    evidence_workspace: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    second_release = evidence_workspace["install_root"] / "release-2043"
    shutil.copytree(evidence_workspace["release"], second_release)
    original_parse = evidence_module._parse_release_manifest
    calls = 0

    def swapping_parse(path: Path) -> tuple[str, dict[str, str]]:
        nonlocal calls
        result = original_parse(path)
        calls += 1
        if calls == 1:
            evidence_workspace["active_link"].unlink()
            evidence_workspace["active_link"].symlink_to(
                second_release, target_is_directory=True
            )
        return result

    monkeypatch.setattr(evidence_module, "_parse_release_manifest", swapping_parse)
    with pytest.raises(EvidenceError, match="changed during validation"):
        seal_report(
            evidence_workspace["source"],
            output_path=evidence_workspace["evidence_root"] / "link-swap.json",
            **_common(evidence_workspace),
        )


def test_stable_reader_detects_path_swap(
    evidence_workspace: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = evidence_workspace["evidence_root"] / "large-capture.bin"
    path.write_bytes(b"a" * (2 * 1024 * 1024))
    original_read = os.read
    swapped = False

    def swapping_read(descriptor: int, count: int) -> bytes:
        nonlocal swapped
        data = original_read(descriptor, count)
        if not swapped:
            swapped = True
            path.rename(path.with_suffix(".original"))
            path.write_bytes(b"b" * (2 * 1024 * 1024))
        return data

    monkeypatch.setattr(evidence_module.os, "read", swapping_read)
    with pytest.raises(EvidenceError, match="changed while being read|replaced during validation"):
        evidence_module._read_stable_file(
            path, "capture", maximum_bytes=3 * 1024 * 1024
        )


def test_evidence_reader_rejects_ancestor_directory_symlink_swap(
    evidence_workspace: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_root = evidence_workspace["evidence_root"]
    nested = evidence_root / "nested"
    nested.mkdir()
    inside = _raw_file(nested, "telegram.txt", evidence_workspace["now"])
    source = deepcopy(evidence_workspace["source"])
    source["platforms"][0]["rawEvidence"] = inside

    outside = evidence_root.parent / "outside-evidence"
    outside.mkdir()
    outside_file = outside / "telegram.txt"
    inside_path = Path(inside["path"])
    outside_file.write_bytes(inside_path.read_bytes())
    outside_time = (evidence_workspace["now"] - timedelta(minutes=2)).timestamp()
    os.utime(outside_file, (outside_time, outside_time))
    outside_file.chmod(0o400)

    original_within = evidence_module._within
    swapped = False

    def swapping_within(path: Path, root: Path, label: str) -> Path:
        nonlocal swapped
        result = original_within(path, root, label)
        if path == inside_path and not swapped:
            swapped = True
            nested.rename(evidence_root / "nested-original")
            nested.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(evidence_module, "_within", swapping_within)
    with pytest.raises(EvidenceError, match="cannot be traversed below"):
        seal_report(
            source,
            output_path=evidence_root / "ancestor-swap.json",
            **_common(evidence_workspace),
        )


def test_collector_approval_is_dedicated_and_not_deploy_ticket(
    evidence_workspace: dict[str, Any],
) -> None:
    source = deepcopy(evidence_workspace["source"])
    source["approvalTicket"] = DEPLOY_TICKET
    common = _common(evidence_workspace)
    common["approval_ticket"] = DEPLOY_TICKET

    with pytest.raises(EvidenceError, match="independent"):
        seal_report(
            source,
            output_path=evidence_workspace["evidence_root"] / "same-ticket.json",
            **common,
        )


def test_report_is_no_clobber_and_sidecar_is_strict(
    evidence_workspace: dict[str, Any],
) -> None:
    output = evidence_workspace["evidence_root"] / "collector-parity.json"
    seal_report(
        evidence_workspace["source"], output_path=output, **_common(evidence_workspace)
    )
    with pytest.raises(EvidenceError, match="already exists"):
        seal_report(
            evidence_workspace["source"], output_path=output, **_common(evidence_workspace)
        )

    sidecar = Path(f"{output}.sha256")
    sidecar.write_text(f"{_sha256(output)}  another.json\n", encoding="ascii")
    with pytest.raises(EvidenceError, match="names another"):
        verify_report(output, **_common(evidence_workspace))


def test_verify_rejects_tampered_raw_evidence_and_stale_report(
    evidence_workspace: dict[str, Any],
) -> None:
    output = evidence_workspace["evidence_root"] / "collector-parity.json"
    report = seal_report(
        evidence_workspace["source"], output_path=output, **_common(evidence_workspace)
    )
    raw_path = Path(report["platforms"][0]["rawEvidence"]["path"])
    raw_path.chmod(0o600)
    raw_path.write_bytes(raw_path.read_bytes() + b"tampered\n")
    raw_path.chmod(0o400)
    with pytest.raises(EvidenceError, match="byte count"):
        verify_report(output, **_common(evidence_workspace))

    # Restore the raw file, then create a correctly checksummed but stale report.
    original = evidence_workspace["source"]["platforms"][0]["rawEvidence"]
    raw_path.chmod(0o600)
    raw_path.write_bytes(b"sanitized live shadow evidence for telegram.txt\n")
    raw_time = (evidence_workspace["now"] - timedelta(minutes=2)).timestamp()
    os.utime(raw_path, (raw_time, raw_time))
    raw_path.chmod(0o400)
    assert _sha256(raw_path) == original["sha256"]
    stored = json.loads(output.read_text(encoding="utf-8"))
    stored["generatedAt"] = _utc(evidence_workspace["now"] - timedelta(days=2))
    _write_json(output, stored)
    _write_sidecar(output, basename_only=True)
    with pytest.raises(EvidenceError, match="future-dated or older"):
        verify_report(output, **_common(evidence_workspace))


def test_verify_rejects_public_report_mode(
    evidence_workspace: dict[str, Any],
) -> None:
    output = evidence_workspace["evidence_root"] / "collector-parity.json"
    seal_report(
        evidence_workspace["source"], output_path=output, **_common(evidence_workspace)
    )
    output.chmod(0o644)
    with pytest.raises(EvidenceError, match="0600"):
        verify_report(output, **_common(evidence_workspace))


@pytest.mark.parametrize(
    "mutation",
    (
        lambda report: report.__setitem__("reportVersion", 1.0),
        lambda report: report["flyway"].__setitem__("migrationCount", 8.0),
        lambda report: report["flyway"]["databaseMigrations"][0].__setitem__(
            "checksum", float(report["flyway"]["databaseMigrations"][0]["checksum"])
        ),
        lambda report: report["duplicates"].__setitem__("outboxEvent", 0.0),
    ),
)
def test_verify_rejects_numeric_json_coercions(
    evidence_workspace: dict[str, Any],
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    output = evidence_workspace["evidence_root"] / "collector-parity.json"
    seal_report(
        evidence_workspace["source"], output_path=output, **_common(evidence_workspace)
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    mutation(report)
    _write_json(output, report)
    _write_sidecar(output, basename_only=True)

    with pytest.raises(EvidenceError):
        verify_report(output, **_common(evidence_workspace))


def test_verify_rejects_changed_deploy_provenance(
    evidence_workspace: dict[str, Any],
) -> None:
    output = evidence_workspace["evidence_root"] / "collector-parity.json"
    sealed = seal_report(
        evidence_workspace["source"], output_path=output, **_common(evidence_workspace)
    )
    assert sealed["release"]["deployTicket"] == DEPLOY_TICKET
    assert sealed["release"]["deployReportSha256"] == _sha256(
        evidence_workspace["deploy_report"]
    )

    deploy_path = evidence_workspace["deploy_report"]
    deploy = json.loads(deploy_path.read_text(encoding="utf-8"))
    deploy["changeTicket"] = "DEPLOY-2043"
    _write_json(deploy_path, deploy)
    _write_sidecar(deploy_path)
    with pytest.raises(EvidenceError, match="bound to the derived active release"):
        verify_report(output, **_common(evidence_workspace))


def test_wrapper_uses_isolated_absolute_module_from_rogue_cwd(
    tmp_path: Path,
) -> None:
    rogue = tmp_path / "rogue"
    rogue.mkdir()
    marker = rogue / "sitecustomize-loaded"
    (rogue / "sitecustomize.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('loaded')\n",
        encoding="utf-8",
    )
    fake_package = rogue / "operations"
    fake_package.mkdir()
    (fake_package / "collector_parity_evidence.py").write_text(
        "raise SystemExit(99)\n", encoding="utf-8"
    )
    shell_marker = rogue / "bash-env-loaded"
    bash_env = rogue / "bash-env"
    bash_env.write_text(f"echo loaded > {shell_marker}\n", encoding="utf-8")
    rogue_bin = rogue / "bin"
    rogue_bin.mkdir()
    path_marker = rogue / "hostile-path-command"
    hostile_dirname = rogue_bin / "dirname"
    hostile_dirname.write_text(
        f"#!/bin/sh\necho loaded > {path_marker}\nexit 99\n", encoding="utf-8"
    )
    hostile_dirname.chmod(0o755)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(rogue)
    environment["BASH_ENV"] = str(bash_env)
    environment["PATH"] = f"{rogue_bin}:/usr/bin:/bin"
    wrapper = ROOT / "operations/bin/collector-parity-evidence"

    result = subprocess.run(
        [str(wrapper), "--help"],
        cwd=rogue,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "external approval remains required" in " ".join(result.stdout.split())
    assert not marker.exists()
    assert not shell_marker.exists()
    assert not path_marker.exists()
    wrapper_source = wrapper.read_text(encoding="utf-8")
    assert wrapper_source.startswith("#!/bin/bash -p\n")
    assert '-I "$project_root/operations/collector_parity_evidence.py"' in wrapper_source


def test_wrapper_rejects_final_symlink_next_to_rogue_python(tmp_path: Path) -> None:
    wrapper = ROOT / "operations/bin/collector-parity-evidence"
    rogue_project = tmp_path / "rogue-project"
    wrapper_alias = rogue_project / "operations/bin/collector-parity-evidence"
    wrapper_alias.parent.mkdir(parents=True)
    wrapper_alias.symlink_to(wrapper)
    rogue_python = rogue_project / ".venv/bin/python"
    rogue_python.parent.mkdir(parents=True)
    marker = rogue_project / "rogue-python-ran"
    rogue_python.write_text(
        f"#!/bin/sh\necho invoked > {marker}\nexit 0\n", encoding="utf-8"
    )
    rogue_python.chmod(0o755)

    result = subprocess.run(
        [str(wrapper_alias), "--help"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 69
    assert "absolute non-symlink path" in result.stderr
    assert not marker.exists()


def test_wrapper_scrubs_macos_pyvenv_launcher(tmp_path: Path) -> None:
    fake_venv = tmp_path / "fake-venv"
    (fake_venv / "bin").mkdir(parents=True)
    site_packages = (
        fake_venv
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    site_packages.mkdir(parents=True)
    (fake_venv / "pyvenv.cfg").write_bytes((ROOT / ".venv/pyvenv.cfg").read_bytes())
    marker = tmp_path / "pyvenv-launcher-loaded"
    (site_packages / "hostile.pth").write_text(
        f"import pathlib; pathlib.Path({str(marker)!r}).write_text('loaded')\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["__PYVENV_LAUNCHER__"] = str(fake_venv / "bin/python")
    wrapper = ROOT / "operations/bin/collector-parity-evidence"

    result = subprocess.run(
        [str(wrapper), "--help"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "external approval remains required" in " ".join(result.stdout.split())
    assert not marker.exists()
    assert "__PYVENV_LAUNCHER__" in wrapper.read_text(encoding="utf-8")


def test_cli_emits_machine_readable_pass_and_failure(
    evidence_workspace: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    source_path = evidence_workspace["evidence_root"] / "source.json"
    _write_json(source_path, evidence_workspace["source"])
    output = evidence_workspace["evidence_root"] / "collector-parity.json"
    common = [
        "--active-release-link",
        str(evidence_workspace["active_link"]),
        "--install-root",
        str(evidence_workspace["install_root"]),
        "--deploy-report",
        str(evidence_workspace["deploy_report"]),
        "--evidence-root",
        str(evidence_workspace["evidence_root"]),
        "--operator",
        OPERATOR,
        "--approval-ticket",
        APPROVAL_TICKET,
        "--source-namespace",
        SOURCE_NAMESPACE,
    ]
    assert main(["seal", *common, "--source", str(source_path), "--output", str(output)]) == 0
    passed = json.loads(capsys.readouterr().out)
    assert passed["status"] == "pass"
    assert passed["command"] == "seal"

    assert main(["verify", *common, "--report", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"

    Path(f"{output}.sha256").write_text("0" * 64 + f"  {output.name}\n")
    assert main(["verify", *common, "--report", str(output)]) == 65
    failed = json.loads(capsys.readouterr().err)
    assert failed["status"] == "fail"
    assert failed["command"] == "verify"
