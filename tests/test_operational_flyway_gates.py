from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import zlib


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = ROOT / "backend/src/main/resources/db/migration"

EXPECTED_MIGRATIONS = (
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


def _flyway_crc32(path: Path) -> int:
    checksum = 0
    with path.open("rb") as stream:
        for line in stream:
            checksum = zlib.crc32(line.rstrip(b"\r\n"), checksum)
    return checksum if checksum < 2**31 else checksum - 2**32


def test_frozen_v1_v8_migration_bytes_match_operational_manifest() -> None:
    files = sorted(MIGRATION_DIR.glob("V*.sql"), key=lambda path: int(path.name[1:].split("__", 1)[0]))
    assert [path.name for path in files] == [entry[1] for entry in EXPECTED_MIGRATIONS]

    for _version, filename, expected_sha256, expected_flyway_checksum in EXPECTED_MIGRATIONS:
        path = MIGRATION_DIR / filename
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256
        assert _flyway_crc32(path) == expected_flyway_checksum


def test_deploy_and_cutover_require_the_complete_frozen_manifest() -> None:
    deploy = (ROOT / "operations/scripts/deploy-shadow.sh").read_text(encoding="utf-8")
    preflight = (ROOT / "operations/scripts/cutover-preflight.sh").read_text(encoding="utf-8")

    assert '.schemaVersion == "8"' in deploy
    assert "actual_migration_files" in deploy
    assert '(.migrations | length) == 8' in deploy
    assert 'all(.migrations[]; .category == "Versioned" and .state == "Success")' in deploy
    assert 'schemaVersion:"8",migrationCount:8' in deploy
    assert "SYMLINKS.sha256" in deploy
    assert deploy.count('validate_release_symlinks "$release_path"') == 3
    assert 'validate_release_symlinks "$release_source"' in deploy
    assert 'validate_release_symlinks "$staging_path"' in deploy
    source_capture = deploy.index('capture_frozen_release_provenance "$release_source"')
    copy = deploy.index(
        'cp -a --no-preserve=ownership -- "$release_source/." "$staging_path/"'
    )
    staging_capture = deploy.index('capture_frozen_release_provenance "$staging_path"')
    move = deploy.index('mv -T -- "$staging_path" "$release_path"')
    installed_capture = deploy.index(
        'capture_frozen_release_provenance "$release_path"', move
    )
    report = deploy.index('--arg releaseManifestSha256 "$release_manifest_sha256"')
    assert source_capture < copy < staging_capture < move < installed_capture < report
    assert deploy.count('capture_frozen_release_provenance "$release_path"') == 3
    assert deploy.rindex('capture_frozen_release_provenance "$release_path"') < report
    assert '"$captured_manifest_sha256" != "$source_manifest_sha256"' in deploy
    assert '"$captured_manifest_sha256" != "$staged_manifest_sha256"' in deploy
    assert 'release_manifest_sha256="$captured_manifest_sha256"' in deploy
    assert 'releaseManifestSha256:$releaseManifestSha256' in deploy
    assert "operator and change ticket must not contain replace-with placeholders" in deploy
    assert "bind_release_source_to_entrypoint" in deploy
    assert '"${artifact_root##*/}" != "$release_id"' in deploy
    assert 'assert_release_source_stable' in deploy
    assert deploy.count('validate_release_tree_trust "$release_source"') >= 1
    assert 'validate_release_tree_trust "$staging_path"' in deploy
    assert 'validate_release_tree_trust "$release_path"' in deploy
    assert 'validate_executable_cohort "$staging_path" installed' in deploy
    assert 'validate_executable_cohort "$release_path" installed' in deploy
    assert deploy.count("assert_installed_release_stable") >= 10
    for required_runtime in (
        "operations/bin/collector-parity-evidence",
        "operations/bin/pg-to-legacy-sync",
        "operations/scripts/switch-routing.sh",
        "operations/scripts/writer-cutover.sh",
        "operations/scripts/rollback.sh",
    ):
        assert required_runtime in deploy
    executable_block = re.search(
        r"^executable_files=\(\n(?P<body>.*?)^\)\n",
        deploy,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert executable_block is not None
    assert set(executable_block.group("body").split()) == {
        "operations/bin/collector-parity-evidence",
        "operations/bin/pg-to-legacy-sync",
        "operations/scripts/backup.sh",
        "operations/scripts/cache-outbox-worker.sh",
        "operations/scripts/collector-preflight.sh",
        "operations/scripts/cutover-preflight.sh",
        "operations/scripts/deploy-shadow.sh",
        "operations/scripts/projection-publisher.sh",
        "operations/scripts/restore-verify.sh",
        "operations/scripts/rollback.sh",
        "operations/scripts/run-maintenance.sh",
        "operations/scripts/switch-routing.sh",
        "operations/scripts/wal-archive.sh",
        "operations/scripts/writer-cutover.sh",
    }
    assert 'find "$staging_path" -type f -exec chmod 0644 {} +' in deploy
    assert 'chmod 0755 "$staging_path/$relative_path"' in deploy
    assert "assert_active_release_ready_for_report" in deploy
    final_gate = deploy.rindex("assert_active_release_ready_for_report")
    report_tmp = deploy.index('report_tmp="$(mktemp', final_gate)
    report_write = deploy.index('>"$report_tmp"', report_tmp)
    assert final_gate < report_tmp < report_write
    assert '>"$report"' not in deploy
    assert '>"$report.sha256"' not in deploy
    assert '|| -e "$report_sidecar" || -L "$report_sidecar"' in deploy
    assert 'mv -T -- "$report_tmp" "$report"' in deploy
    assert 'mv -T -- "$report_sidecar_tmp" "$report_sidecar"' in deploy
    assert (
        'mv -Tf -- "$current_report_tmp" "$DEPLOY_REPORT_DIR/current.json"'
        in deploy
    )
    assert (
        'mv -Tf -- "$current_sidecar_tmp" "$DEPLOY_REPORT_DIR/current.json.sha256"'
        in deploy
    )
    assert '.flyway.schemaVersion == "8"' in preflight
    assert '.releaseManifestSha256 | test("^[0-9a-f]{64}$")' in preflight
    assert ".flyway.migrationCount == 8" in preflight
    assert ".database.flywaySchemaVersion == 8" in preflight
    assert ".database.flywayMigrationCount == 8" in preflight
    assert preflight.count('verify_exact_release_manifest "$current_release_path"') == 2
    assert 'validate_release_symlinks "$tree"' in preflight

    for version, filename, sha256, _flyway_checksum in EXPECTED_MIGRATIONS:
        assert f"backend/src/main/resources/db/migration/{filename}" in deploy
        assert sha256 in deploy
        assert f".flyway.v{version}Sha256 == \"{sha256}\"" in preflight
        assert f"v{version}Sha256" in deploy
        assert (
            f'{{version:"{version}",script:"{filename}",checksum:{_flyway_checksum}}}'
            in preflight
        )


def _shell_function(source: str, name: str) -> str:
    match = re.search(
        rf"^{re.escape(name)}\(\) \{{\n.*?^\}}\n",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, name
    return match.group(0)


def test_deploy_provenance_capture_rejects_changed_staging_migration(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release"
    migration_root = release_root / "backend/src/main/resources/db/migration"
    migration_root.mkdir(parents=True)
    (release_root / "SHA256SUMS").write_text("manifest bytes\n", encoding="ascii")
    for _version, filename, _sha256, _checksum in EXPECTED_MIGRATIONS:
        (migration_root / filename).write_bytes((MIGRATION_DIR / filename).read_bytes())

    deploy = (ROOT / "operations/scripts/deploy-shadow.sh").read_text(
        encoding="utf-8"
    )
    function = _shell_function(deploy, "capture_frozen_release_provenance")
    command = f"""
set -Eeuo pipefail
{function}
capture_frozen_release_provenance "$1"
printf '%s\n' "$captured_manifest_sha256"
"""
    valid = subprocess.run(
        ["bash", "-c", command, "deploy-provenance-test", str(release_root)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert valid.returncode == 0, valid.stderr
    assert valid.stdout.strip() == hashlib.sha256(
        (release_root / "SHA256SUMS").read_bytes()
    ).hexdigest()

    (migration_root / "V8__legacy_overview_projection.sql").write_text(
        "changed during staging\n",
        encoding="utf-8",
    )
    changed = subprocess.run(
        ["bash", "-c", command, "deploy-provenance-test", str(release_root)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert changed.returncode != 0
    assert "checksum mismatch" in changed.stderr


def _write_symlink_manifest(release_root: Path) -> None:
    symlink_records = []
    for path in release_root.rglob("*"):
        if path.is_symlink():
            relative_name = path.relative_to(release_root).as_posix()
            raw_target = os.readlink(path)
            target_sha256 = hashlib.sha256(os.fsencode(raw_target)).hexdigest()
            symlink_records.append(f"{target_sha256}  {relative_name}\n")
    (release_root / "SYMLINKS.sha256").write_text(
        "".join(sorted(symlink_records)),
        encoding="ascii",
    )


def _write_sha256sums(release_root: Path) -> None:
    regular_records = []
    for path in release_root.rglob("*"):
        if (
            path.is_file()
            and not path.is_symlink()
            and path.name != "SHA256SUMS"
        ):
            relative_name = path.relative_to(release_root).as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            regular_records.append(f"{digest}  {relative_name}\n")
    (release_root / "SHA256SUMS").write_text(
        "".join(sorted(regular_records)),
        encoding="ascii",
    )


def _write_release_manifests(release_root: Path) -> None:
    _write_symlink_manifest(release_root)
    _write_sha256sums(release_root)


def _active_release_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    install_root = tmp_path / "m-ranked" / "releases"
    release_root = install_root / "release-2026-09-05"
    release_root.mkdir(parents=True)
    payload = release_root / "payload.txt"
    payload.write_text("immutable release payload\n", encoding="utf-8")
    alternate = release_root / "alternate.txt"
    alternate.write_text("alternate immutable payload\n", encoding="utf-8")
    (release_root / "payload-link").symlink_to("payload.txt")
    package_root = release_root / "frontend/packages/example"
    package_root.mkdir(parents=True)
    (package_root / "index.js").write_text("export default 1;\n", encoding="utf-8")
    node_modules = release_root / "frontend/node_modules"
    node_modules.mkdir(parents=True)
    (node_modules / "example").symlink_to(
        "../packages/example",
        target_is_directory=True,
    )
    _write_release_manifests(release_root)
    manifest = release_root / "SHA256SUMS"
    release_root.chmod(0o755)
    for path in release_root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            path.chmod(0o644)
    current_link = tmp_path / "m-ranked" / "current"
    current_link.symlink_to(release_root, target_is_directory=True)

    flyway = {
        "validated": True,
        "schemaVersion": "8",
        "migrationCount": 8,
        **{
            f"v{version}Sha256": sha256
            for version, _filename, sha256, _checksum in EXPECTED_MIGRATIONS
        },
    }
    report = tmp_path / "deploy.json"
    report.write_text(
        json.dumps(
            {
                "status": "pass",
                "releasePath": str(release_root),
                "releaseId": release_root.name,
                "releaseManifestSha256": hashlib.sha256(
                    manifest.read_bytes()
                ).hexdigest(),
                "flyway": flyway,
                "projectionPublisherActive": True,
            }
        ),
        encoding="utf-8",
    )
    report.chmod(0o600)
    sidecar = Path(f"{report}.sha256")
    sidecar.write_text(
        f"{hashlib.sha256(report.read_bytes()).hexdigest()}  {report.name}\n",
        encoding="ascii",
    )
    sidecar.chmod(0o600)
    return install_root, current_link, report


def _run_active_release_gate(
    install_root: Path,
    current_link: Path,
    report: Path,
) -> subprocess.CompletedProcess[str]:
    preflight = (ROOT / "operations/scripts/cutover-preflight.sh").read_text(
        encoding="utf-8"
    )
    definitions = "\n".join(
        _shell_function(preflight, name)
        for name in (
            "require_readable",
            "file_mode",
            "file_identity",
            "check_not_group_world_writable",
            "check_sha256_sidecar",
            "validate_release_symlinks",
            "verify_exact_release_manifest",
            "check_active_release_gate",
        )
    )
    test_root_regex = rf"^{re.escape(str(install_root.parent))}/[A-Za-z0-9._/-]+$"
    script = f"""
set -Eeuo pipefail
failures=0
fail() {{ failures=$((failures + 1)); echo "FAIL: $*" >&2; }}
pass() {{ :; }}
deploy_release_id=""
deploy_manifest_sha256=""
deploy_release_path=""
{definitions}
if check_active_release_gate "$1" "$2" "$3" "$4"; then
  printf '%s|%s|%s\n' \
    "$deploy_release_id" "$deploy_manifest_sha256" "$deploy_release_path"
else
  exit 1
fi
"""
    return subprocess.run(
        [
            "bash",
            "-c",
            script,
            "active-release-gate-test",
            str(report),
            str(install_root),
            str(current_link),
            test_root_regex,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def _run_release_symlink_validator(
    script_path: Path,
    release_root: Path,
) -> subprocess.CompletedProcess[str]:
    source = script_path.read_text(encoding="utf-8")
    function = _shell_function(source, "validate_release_symlinks")
    script = f"""
set -Eeuo pipefail
{function}
validate_release_symlinks "$1"
"""
    return subprocess.run(
        [
            "bash",
            "-c",
            script,
            "release-symlink-validator-test",
            str(release_root),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def _symlink_validator_scripts() -> tuple[Path, Path]:
    return (
        ROOT / "operations/scripts/deploy-shadow.sh",
        ROOT / "operations/scripts/cutover-preflight.sh",
    )


def _rewrite_deploy_report(report: Path, payload: dict[str, object]) -> None:
    report.write_text(json.dumps(payload), encoding="utf-8")
    sidecar = Path(f"{report}.sha256")
    sidecar.write_text(
        f"{hashlib.sha256(report.read_bytes()).hexdigest()}  {report.name}\n",
        encoding="ascii",
    )
    report.chmod(0o600)
    sidecar.chmod(0o600)


def test_active_release_gate_executes_exact_tree_and_report_binding(
    tmp_path: Path,
) -> None:
    install_root, current_link, report = _active_release_fixture(tmp_path)
    result = _run_active_release_gate(install_root, current_link, report)

    assert result.returncode == 0, result.stderr
    expected_hash = hashlib.sha256(
        (install_root / "release-2026-09-05" / "SHA256SUMS").read_bytes()
    ).hexdigest()
    expected_release = install_root / "release-2026-09-05"
    assert result.stdout.strip() == (
        f"release-2026-09-05|{expected_hash}|{expected_release}"
    )


def test_release_symlink_manifest_rejects_retargeting_and_unlisted_links(
    tmp_path: Path,
) -> None:
    install_root, _current_link, _report = _active_release_fixture(tmp_path)
    release_root = install_root / "release-2026-09-05"
    payload_link = release_root / "payload-link"

    for script_path in _symlink_validator_scripts():
        valid = _run_release_symlink_validator(script_path, release_root)
        assert valid.returncode == 0, (script_path.name, valid.stderr)

    payload_link.unlink()
    payload_link.symlink_to("alternate.txt")
    for script_path in _symlink_validator_scripts():
        changed = _run_release_symlink_validator(script_path, release_root)
        assert changed.returncode != 0, script_path.name

    payload_link.unlink()
    payload_link.symlink_to("payload.txt")
    (release_root / "unlisted-link").symlink_to("payload.txt")
    for script_path in _symlink_validator_scripts():
        unlisted = _run_release_symlink_validator(script_path, release_root)
        assert unlisted.returncode != 0, script_path.name


def test_release_symlink_change_requires_manifest_and_deploy_report_rebinding(
    tmp_path: Path,
) -> None:
    install_root, current_link, report = _active_release_fixture(tmp_path)
    release_root = install_root / "release-2026-09-05"
    payload_link = release_root / "payload-link"
    payload_link.unlink()
    payload_link.symlink_to("alternate.txt")

    _write_symlink_manifest(release_root)
    for script_path in _symlink_validator_scripts():
        unbound_link_inventory = _run_release_symlink_validator(
            script_path,
            release_root,
        )
        assert unbound_link_inventory.returncode != 0, script_path.name
    assert _run_active_release_gate(install_root, current_link, report).returncode != 0

    _write_sha256sums(release_root)
    for script_path in _symlink_validator_scripts():
        rebound_link_inventory = _run_release_symlink_validator(
            script_path,
            release_root,
        )
        assert rebound_link_inventory.returncode == 0, (
            script_path.name,
            rebound_link_inventory.stderr,
        )
    assert _run_active_release_gate(install_root, current_link, report).returncode != 0


def test_release_symlink_manifest_rejects_external_and_noncanonical_inventory(
    tmp_path: Path,
) -> None:
    install_root, _current_link, _report = _active_release_fixture(tmp_path)
    release_root = install_root / "release-2026-09-05"
    returning_alias = tmp_path / "outside-alias-returning-inside"
    returning_alias.symlink_to(release_root / "payload.txt")
    returning_link = release_root / "returning-link"
    returning_link.symlink_to(os.path.relpath(returning_alias, release_root))
    _write_release_manifests(release_root)
    for script_path in _symlink_validator_scripts():
        returning = _run_release_symlink_validator(script_path, release_root)
        assert returning.returncode != 0, script_path.name
    returning_link.unlink()
    returning_alias.unlink()

    outside = tmp_path / "outside.txt"
    outside.write_text("outside release\n", encoding="utf-8")
    (release_root / "external-link").symlink_to(outside)
    _write_release_manifests(release_root)

    for script_path in _symlink_validator_scripts():
        external = _run_release_symlink_validator(script_path, release_root)
        assert external.returncode != 0, script_path.name

    (release_root / "external-link").unlink()
    _write_release_manifests(release_root)
    symlink_manifest = release_root / "SYMLINKS.sha256"
    lines = symlink_manifest.read_text(encoding="ascii").splitlines(keepends=True)
    assert len(lines) >= 2
    symlink_manifest.write_text("".join(reversed(lines)), encoding="ascii")
    for script_path in _symlink_validator_scripts():
        noncanonical = _run_release_symlink_validator(script_path, release_root)
        assert noncanonical.returncode != 0, script_path.name

    _write_release_manifests(release_root)
    (release_root / "unsafe-target-link").symlink_to("payload.txt\n")
    _write_release_manifests(release_root)
    for script_path in _symlink_validator_scripts():
        unsafe_target = _run_release_symlink_validator(script_path, release_root)
        assert unsafe_target.returncode != 0, script_path.name


def test_release_symlink_manifest_accepts_canonical_empty_inventory(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release-without-links"
    release_root.mkdir()
    (release_root / "payload.txt").write_text("payload\n", encoding="utf-8")
    _write_release_manifests(release_root)
    assert (release_root / "SYMLINKS.sha256").read_bytes() == b""

    for script_path in _symlink_validator_scripts():
        empty_inventory = _run_release_symlink_validator(script_path, release_root)
        assert empty_inventory.returncode == 0, (
            script_path.name,
            empty_inventory.stderr,
        )


def test_active_release_gate_rejects_stale_or_tampered_provenance(
    tmp_path: Path,
) -> None:
    install_root, current_link, report = _active_release_fixture(tmp_path)
    valid_report = json.loads(report.read_text(encoding="utf-8"))

    for field, invalid_value in (
        ("releasePath", str(install_root / "other-release")),
        ("releaseId", "other-release"),
        ("releaseManifestSha256", "f" * 64),
    ):
        changed = deepcopy(valid_report)
        changed[field] = invalid_value
        _rewrite_deploy_report(report, changed)
        result = _run_active_release_gate(install_root, current_link, report)
        assert result.returncode != 0, field

    _rewrite_deploy_report(report, valid_report)
    extra = install_root / "release-2026-09-05" / "unlisted.txt"
    extra.write_text("not covered by SHA256SUMS\n", encoding="utf-8")
    assert _run_active_release_gate(install_root, current_link, report).returncode != 0
    extra.unlink()

    payload = install_root / "release-2026-09-05" / "payload.txt"
    payload.write_text("changed after deployment\n", encoding="utf-8")
    assert _run_active_release_gate(install_root, current_link, report).returncode != 0


def test_active_release_gate_rejects_non_private_report_and_indirect_link(
    tmp_path: Path,
) -> None:
    install_root, current_link, report = _active_release_fixture(tmp_path)
    report.chmod(0o620)
    assert _run_active_release_gate(install_root, current_link, report).returncode != 0

    report.chmod(0o600)
    sidecar = Path(f"{report}.sha256")
    sidecar.chmod(0o602)
    assert _run_active_release_gate(install_root, current_link, report).returncode != 0

    sidecar.chmod(0o600)
    intermediate = install_root / "release-alias"
    intermediate.symlink_to(install_root / "release-2026-09-05", target_is_directory=True)
    current_link.unlink()
    current_link.symlink_to(intermediate, target_is_directory=True)
    assert _run_active_release_gate(install_root, current_link, report).returncode != 0


def _run_collector_consumer(
    tmp_path: Path,
    *,
    verifier_status: str = "pass",
    verifier_exit: int = 0,
    active_release_is_outside: bool = False,
    active_gate_succeeded: bool = True,
    execution_marker: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    install_root = tmp_path / "releases"
    release = install_root / "release-collector-gate"
    active_release = release
    if active_release_is_outside:
        active_release = tmp_path / "outside-release"
    verifier = active_release / "operations/bin/collector-parity-evidence"
    verifier.parent.mkdir(parents=True)
    current_link = tmp_path / "current"
    current_link.symlink_to(active_release, target_is_directory=True)
    report = tmp_path / "collector.json"
    report.write_text("{}\n", encoding="utf-8")
    verifier_output = json.dumps(
        {
            "command": "verify",
            "generatedAt": "2026-09-05T00:00:00Z",
            "report": str(report),
            "releaseId": release.name,
            "status": verifier_status,
        },
        sort_keys=True,
    )
    marker_command = ""
    if execution_marker is not None:
        marker_command = f"printf executed > {json.dumps(str(execution_marker))}\n"
    verifier.write_text(
        "#!/bin/bash\n"
        + marker_command
        + f"printf '%s\\n' {json.dumps(verifier_output)}\n"
        + f"exit {verifier_exit}\n",
        encoding="utf-8",
    )
    verifier.chmod(0o755)

    preflight = (ROOT / "operations/scripts/cutover-preflight.sh").read_text(
        encoding="utf-8"
    )
    function = _shell_function(preflight, "check_collector_parity_gate")
    script = f"""
set -Eeuo pipefail
failures=0
fail() {{ failures=$((failures + 1)); }}
pass() {{ :; }}
{function}
check_collector_parity_gate \
  "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9" "${{10}}"
"""
    return subprocess.run(
        [
            "bash",
            "-c",
            script,
            "collector-consumer-test",
            str(report),
            str(tmp_path),
            str(release) if active_gate_succeeded else "",
            str(current_link),
            str(install_root),
            str(tmp_path / "deploy.json"),
            "operator-alice",
            "COLLECTOR-APPROVAL-2042",
            "m-ranked-production",
            "86400",
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_cutover_consumer_requires_verifier_exit_and_machine_pass(tmp_path: Path) -> None:
    accepted = _run_collector_consumer(tmp_path / "accepted")
    assert accepted.returncode == 0, accepted.stderr

    wrong_status = _run_collector_consumer(
        tmp_path / "wrong-status", verifier_status="fail"
    )
    assert wrong_status.returncode != 0

    rejected = _run_collector_consumer(
        tmp_path / "rejected", verifier_exit=65
    )
    assert rejected.returncode != 0


def test_cutover_consumer_never_executes_out_of_root_current_after_gate_failure(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "malicious-verifier-executed"
    rejected = _run_collector_consumer(
        tmp_path,
        active_release_is_outside=True,
        active_gate_succeeded=False,
        execution_marker=marker,
    )

    assert rejected.returncode != 0
    assert not marker.exists()
    preflight = (ROOT / "operations/scripts/cutover-preflight.sh").read_text(
        encoding="utf-8"
    )
    consumer = _shell_function(preflight, "check_collector_parity_gate")
    assert 'local release_path="$3"' in consumer
    assert 'release_path="$(readlink -f' not in consumer
    assert 'if [[ -z "$deploy_release_path" ]]' in preflight
    assert (
        '"$deploy_release_path/operations/bin/collector-parity-evidence"'
        in preflight
    )


def test_writer_gate_replaces_legacy_collector_booleans_with_strict_verifier() -> None:
    preflight = (ROOT / "operations/scripts/cutover-preflight.sh").read_text(
        encoding="utf-8"
    )
    deploy = (ROOT / "operations/scripts/deploy-shadow.sh").read_text(
        encoding="utf-8"
    )
    env_example = (ROOT / "operations/env/cutover.env.example").read_text(
        encoding="utf-8"
    )

    assert ".checks.fourPlatforms" not in preflight
    assert 'exec /bin/bash -p "$verifier" verify' in preflight
    assert "operations/collector_parity_evidence.py" in deploy
    assert "operations/bin/collector-parity-evidence" in deploy
    assert "COLLECTOR_PARITY_REPORT=" in env_example
    assert "COLLECTOR_PARITY_EVIDENCE_ROOT=" in env_example
    assert "COLLECTOR_PARITY_MAX_AGE_SECONDS=86400" in env_example
    assert "COLLECTOR_PARITY_APPROVAL_TICKET=" in env_example


def test_cutover_placeholder_guard_rejects_approval_templates() -> None:
    preflight = (ROOT / "operations/scripts/cutover-preflight.sh").read_text(
        encoding="utf-8"
    )
    guard = _shell_function(preflight, "reject_placeholder_value")
    script = f"""
set -Eeuo pipefail
failures=0
fail() {{ failures=$((failures + 1)); }}
{guard}
if reject_placeholder_value "$1"; then
  exit 9
fi
test "$failures" -eq 1
"""
    for name in (
        "OPERATOR_ID",
        "CHANGE_TICKET",
        "MIGRATION_SOURCE_NAMESPACE",
        "REVERSE_SYNC_APPROVAL_TICKET",
    ):
        result = subprocess.run(
            ["bash", "-c", script, "placeholder-test", name],
            env={name: f"replace-with-{name.lower()}"},
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, (name, result.stderr)


def test_restore_verifier_requires_exact_v1_v8_history() -> None:
    restore = (ROOT / "operations/scripts/restore-verify.sh").read_text(encoding="utf-8")

    assert "migration_count <> 8 OR latest_migration <> 8" in restore
    assert "ARRAY['1', '2', '3', '4', '5', '6', '7', '8']::text[]" in restore
    assert "WHERE version IS NULL" in restore
    assert "'flywayMigrations'" in restore
    for version, filename, _sha256, flyway_checksum in EXPECTED_MIGRATIONS:
        assert f"('{version}', '{filename}', {flyway_checksum})" in restore


def test_writer_cutover_binds_reverse_preflight_to_the_new_s_final() -> None:
    writer = (ROOT / "operations/scripts/writer-cutover.sh").read_text(
        encoding="utf-8"
    )

    backup = writer.index(
        '"$python_bin" -m migration.bridge backup "$LEGACY_SQLITE_PATH" "$s_final"'
    )
    source_hash = writer.index('s_final_sha256="$(sha256sum "$s_final"')
    imported = writer.index(
        'PGPASSFILE="$MIGRATION_PGPASSFILE" "$python_bin" -m migration.bridge import "$s_final"'
    )
    reconciled = writer.index(
        'if ! jq -e --arg sFinal "$s_final" --arg sFinalSha256 "$s_final_sha256"'
    )
    reverse_preflight = writer.index(
        'reverse_preflight_json="$("$REVERSE_SYNC_EXECUTABLE" preflight)"'
    )
    reverse_start = writer.index('"$REVERSE_SYNC_EXECUTABLE" start')

    assert backup < source_hash < imported < reconciled < reverse_preflight < reverse_start
    assert writer.count('"$REVERSE_SYNC_EXECUTABLE" preflight') == 1
    assert ".source.source_path == $sFinal" in writer
    assert ".source.source_sha256 == $sFinalSha256" in writer
    assert ".bridge.source_sha256 == $sFinalSha256" in writer
    assert ".bridge.batch_id == .batch_id" in writer
    assert ".postgres.sFinalBatchId == $batchId" in writer
    assert ".postgres.sFinalSourceSha256 == $sourceSha256" in writer


def _writer_jq_filter(start_marker: str, end_marker: str) -> str:
    writer = (ROOT / "operations/scripts/writer-cutover.sh").read_text(
        encoding="utf-8"
    )
    return writer.split(start_marker, 1)[1].split(end_marker, 1)[0]


def _jq_filter_accepts(
    jq_filter: str,
    payload: dict[str, object],
    *arguments: str,
) -> bool:
    result = subprocess.run(
        ["jq", "-e", *arguments, jq_filter],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def test_writer_cutover_validates_exact_s_final_and_reverse_binding() -> None:
    source_path = "/var/lib/m-ranked/snapshots/S-final.sqlite3"
    source_sha256 = "a" * 64
    batch_id = "11111111-1111-4111-8111-111111111111"
    import_filter = _writer_jq_filter(
        'if ! jq -e --arg sFinal "$s_final" --arg sFinalSha256 "$s_final_sha256" \'\n',
        '\n  \' "$report_json" >/dev/null; then',
    )
    import_report: dict[str, object] = {
        "report_type": "post-import-reconciliation",
        "report_version": 1,
        "gate": {"status": "pass", "critical_mismatches": 0},
        "source": {
            "source_path": source_path,
            "source_sha256": source_sha256,
            "quick_check": "ok",
            "foreign_key_violations": 0,
        },
        "batch_id": batch_id,
        "bridge": {
            "batch_id": batch_id,
            "source_sha256": source_sha256,
            "dry_run": False,
            "finished_at": "2026-09-04T12:00:00+00:00",
        },
    }
    import_arguments = (
        "--arg", "sFinal", source_path,
        "--arg", "sFinalSha256", source_sha256,
    )
    assert _jq_filter_accepts(import_filter, import_report, *import_arguments)
    for invalid_report in (
        {**import_report, "batch_id": "22222222-2222-4222-8222-222222222222"},
        {
            **import_report,
            "source": {**import_report["source"], "source_path": "/stale.sqlite3"},
        },
        {
            **import_report,
            "bridge": {**import_report["bridge"], "source_sha256": "b" * 64},
        },
    ):
        assert not _jq_filter_accepts(import_filter, invalid_report, *import_arguments)

    reverse_filter = _writer_jq_filter(
        '    --arg sourceSha256 "$s_final_sha256" \'\n',
        '\n    \' <<<"$reverse_preflight_json" >/dev/null; then',
    )
    reverse_report: dict[str, object] = {
        "command": "preflight",
        "status": "pass",
        "sourceNamespace": "production/source",
        "postgres": {
            "aliasMappingsUnambiguous": True,
            "singlePrimaryIdentity": True,
            "sFinalBatchId": batch_id,
            "sFinalSourceSha256": source_sha256,
        },
        "legacySqlite": {"quickCheck": "ok"},
    }
    reverse_arguments = (
        "--arg", "namespace", "production/source",
        "--arg", "batchId", batch_id,
        "--arg", "sourceSha256", source_sha256,
    )
    assert _jq_filter_accepts(reverse_filter, reverse_report, *reverse_arguments)
    changed_binding = deepcopy(reverse_report)
    postgres = changed_binding["postgres"]
    assert isinstance(postgres, dict)
    postgres["sFinalBatchId"] = "22222222-2222-4222-8222-222222222222"
    assert not _jq_filter_accepts(reverse_filter, changed_binding, *reverse_arguments)


def _reverse_rehearsal_jq_filter() -> str:
    preflight = (ROOT / "operations/scripts/cutover-preflight.sh").read_text(
        encoding="utf-8"
    )
    function = preflight.split(
        "check_reverse_sync_rehearsal_gate() {", 1
    )[1].split("check_sha256_sidecar() {", 1)[0]
    match = re.search(
        r"local contract_filter='(?P<filter>.*?)'\n  if jq -e",
        function,
        flags=re.DOTALL,
    )
    assert match is not None
    return match.group("filter")


def _reverse_rehearsal_evidence() -> dict[str, object]:
    return {
        "reportType": "reverse-sync-rehearsal",
        "reportVersion": 3,
        "status": "pass",
        "environment": "production-like",
        "generatedAt": "2026-09-05T12:00:00+00:00",
        "release": {
            "id": "release-2026-09-05",
            "sha256SumsSha256": "a" * 64,
        },
        "operator": "gate-w-operator",
        "changeTicket": "GATE-W-APPROVAL",
        "sourceNamespace": "m-ranked-production",
        "database": "mranked_rehearsal_20260905",
        "flyway": {
            "schemaVersion": 8,
            "migrationCount": 8,
            "fileSha256": {
                filename: sha256
                for _version, filename, sha256, _checksum in EXPECTED_MIGRATIONS
            },
            "databaseMigrations": [
                {
                    "version": version,
                    "script": filename,
                    "checksum": checksum,
                    "success": True,
                }
                for version, filename, _sha256, checksum in EXPECTED_MIGRATIONS
            ],
        },
        "platforms": ["telegram", "vk", "max", "rutube"],
        "replay": {"runCount": 2, "idempotent": True},
        "duplicates": {
            "observationCount": 0,
            "identityCount": 0,
            "primaryIdentityCount": 0,
            "snapshotCount": 0,
        },
        "preservation": {
            "publicationMismatches": 0,
            "identityMismatches": 0,
            "snapshotMismatches": 0,
            "aliasMismatches": 0,
        },
        "forwardReconciliation": {"status": "pass", "criticalMismatches": 0},
        "reverseSync": {
            "status": "stopped",
            "journalStateVersion": 3,
            "baselineRevisionCount": 1,
            "baselineRevisionSetSha256": "b" * 64,
            "fixedRevisionCount": 4,
            "fixedRevisionSetSha256": "c" * 64,
            "planSha256": "d" * 64,
        },
        "sFinal": {
            "batchId": "11111111-1111-4111-8111-111111111111",
            "sourceSha256": "e" * 64,
            "gate": "pass",
        },
    }


def _jq_accepts_rehearsal(payload: dict[str, object]) -> bool:
    return _jq_filter_accepts(
        _reverse_rehearsal_jq_filter(),
        payload,
        "--arg", "releaseId", "release-2026-09-05",
        "--arg", "manifestSha256", "a" * 64,
        "--arg", "sourceNamespace", "m-ranked-production",
        "--arg", "approvalTicket", "GATE-W-APPROVAL",
        "--arg", "operator", "gate-w-operator",
    )


def test_reverse_sync_rehearsal_gate_requires_complete_positive_evidence() -> None:
    preflight = (ROOT / "operations/scripts/cutover-preflight.sh").read_text(
        encoding="utf-8"
    )

    assert _jq_accepts_rehearsal(_reverse_rehearsal_evidence())
    assert not _jq_accepts_rehearsal({"status": "pass"})
    assert "check_reverse_sync_rehearsal_gate \\" in preflight
    assert '"$REVERSE_SYNC_REHEARSAL_REPORT" \\' in preflight
    assert (
        'check_json_gate "$REVERSE_SYNC_REHEARSAL_REPORT"'
        not in preflight
    )


def test_reverse_sync_rehearsal_gate_fails_when_any_evidence_is_absent() -> None:
    required_paths = (
        ("reportType",),
        ("reportVersion",),
        ("status",),
        ("environment",),
        ("generatedAt",),
        ("release", "id"),
        ("release", "sha256SumsSha256"),
        ("operator",),
        ("changeTicket",),
        ("sourceNamespace",),
        ("database",),
        ("flyway", "schemaVersion"),
        ("flyway", "migrationCount"),
        ("flyway", "fileSha256"),
        ("flyway", "databaseMigrations"),
        ("platforms",),
        ("replay", "runCount"),
        ("replay", "idempotent"),
        ("duplicates", "observationCount"),
        ("duplicates", "identityCount"),
        ("duplicates", "primaryIdentityCount"),
        ("duplicates", "snapshotCount"),
        ("preservation", "publicationMismatches"),
        ("preservation", "identityMismatches"),
        ("preservation", "snapshotMismatches"),
        ("preservation", "aliasMismatches"),
        ("forwardReconciliation", "status"),
        ("forwardReconciliation", "criticalMismatches"),
        ("reverseSync", "status"),
        ("reverseSync", "journalStateVersion"),
        ("reverseSync", "baselineRevisionCount"),
        ("reverseSync", "baselineRevisionSetSha256"),
        ("reverseSync", "fixedRevisionCount"),
        ("reverseSync", "fixedRevisionSetSha256"),
        ("reverseSync", "planSha256"),
        ("sFinal", "batchId"),
        ("sFinal", "sourceSha256"),
        ("sFinal", "gate"),
    )

    for path in required_paths:
        evidence = deepcopy(_reverse_rehearsal_evidence())
        parent = evidence
        for key in path[:-1]:
            child = parent[key]
            assert isinstance(child, dict)
            parent = child
        parent.pop(path[-1])
        assert not _jq_accepts_rehearsal(evidence), path


def test_reverse_sync_rehearsal_gate_rejects_incomplete_or_false_proofs() -> None:
    invalid_changes = (
        (("reportType",), "other"),
        (("reportVersion",), 2),
        (("reportVersion",), "3"),
        (("environment",), "disposable-postgresql-integration"),
        (("release", "id"), "other-release"),
        (("release", "sha256SumsSha256"), "f" * 64),
        (("operator",), "other-operator"),
        (("changeTicket",), "OTHER-APPROVAL"),
        (("sourceNamespace",), "other-namespace"),
        (("database",), ""),
        (("database",), "postgresql://user:pass@host/db"),
        (("flyway", "schemaVersion"), 7),
        (("flyway", "schemaVersion"), "8"),
        (("flyway", "migrationCount"), 7),
        (("flyway", "fileSha256", "V8__legacy_overview_projection.sql"), "f" * 64),
        (("flyway", "databaseMigrations", 7, "checksum"), -1),
        (("platforms",), ["telegram", "vk", "max", "max"]),
        (("platforms",), ["telegram", "vk", "max", "rutube", "other"]),
        (("replay", "runCount"), 1),
        (("replay", "runCount"), 2.5),
        (("replay", "idempotent"), False),
        (("duplicates", "observationCount"), 1),
        (("duplicates", "identityCount"), 1),
        (("duplicates", "primaryIdentityCount"), 1),
        (("duplicates", "snapshotCount"), 1),
        (("preservation", "publicationMismatches"), 1),
        (("preservation", "identityMismatches"), 1),
        (("preservation", "snapshotMismatches"), 1),
        (("preservation", "aliasMismatches"), 1),
        (("forwardReconciliation", "status"), "fail"),
        (("forwardReconciliation", "criticalMismatches"), 1),
        (("reverseSync", "status"), "verified"),
        (("reverseSync", "journalStateVersion"), 2),
        (("reverseSync", "baselineRevisionCount"), 0),
        (("reverseSync", "baselineRevisionSetSha256"), "B" * 64),
        (("reverseSync", "fixedRevisionCount"), 2.5),
        (("reverseSync", "fixedRevisionCount"), 3),
        (("reverseSync", "fixedRevisionSetSha256"), "short"),
        (("reverseSync", "planSha256"), None),
        (("sFinal", "batchId"), "not-a-uuid"),
        (("sFinal", "sourceSha256"), "E" * 64),
        (("sFinal", "gate"), "fail"),
    )

    for path, invalid_value in invalid_changes:
        evidence = deepcopy(_reverse_rehearsal_evidence())
        parent = evidence
        for key in path[:-1]:
            child = parent[key] if isinstance(key, str) else parent[key]
            assert isinstance(child, (dict, list))
            parent = child
        final_key = path[-1]
        parent[final_key] = invalid_value
        assert not _jq_accepts_rehearsal(evidence), (path, invalid_value)


def test_reverse_sync_rehearsal_gate_rejects_additional_keys() -> None:
    for path in ((), ("release",), ("flyway",), ("duplicates",), ("sFinal",)):
        evidence = deepcopy(_reverse_rehearsal_evidence())
        parent = evidence
        for key in path:
            child = parent[key]
            assert isinstance(child, dict)
            parent = child
        parent["unexpected"] = True
        assert not _jq_accepts_rehearsal(evidence), path


def test_reverse_sync_rehearsal_gate_requires_fresh_checksummed_evidence() -> None:
    preflight = (ROOT / "operations/scripts/cutover-preflight.sh").read_text(
        encoding="utf-8"
    )
    env_example = (ROOT / "operations/env/cutover.env.example").read_text(
        encoding="utf-8"
    )

    assert 'check_sha256_sidecar "$path" "reverse-sync rehearsal report"' in preflight
    assert 'check_not_group_world_writable "$path" "reverse-sync rehearsal report"' in preflight
    assert 'check_file_age_gate "$path" "reverse-sync rehearsal report"' in preflight
    assert 'check_file_age_gate "$path.sha256"' in preflight
    assert 'date -u --date="$generated_at" +%s' in preflight
    assert 'REVERSE_SYNC_REHEARSAL_MAX_AGE_SECONDS="${REVERSE_SYNC_REHEARSAL_MAX_AGE_SECONDS:-86400}"' in preflight
    assert "REVERSE_SYNC_REHEARSAL_MAX_AGE_SECONDS=86400" in env_example
    assert "REVERSE_SYNC_APPROVAL_TICKET=" in env_example
    assert "MRANKED_INSTALL_ROOT=/opt/m-ranked/releases" in env_example
    assert "MRANKED_CURRENT_LINK=/opt/m-ranked/current" in env_example
    assert 'require_value REVERSE_SYNC_APPROVAL_TICKET' in preflight
    assert 'reject_placeholder_value REVERSE_SYNC_APPROVAL_TICKET' in preflight
    assert 'reject_placeholder_value MIGRATION_SOURCE_NAMESPACE' in preflight
    assert 'require_value MIGRATION_SOURCE_NAMESPACE' in preflight


def test_cutover_scripts_remain_valid_bash() -> None:
    for script in (
        ROOT / "operations/scripts/cutover-preflight.sh",
        ROOT / "operations/scripts/deploy-shadow.sh",
        ROOT / "operations/scripts/switch-routing.sh",
        ROOT / "operations/scripts/writer-cutover.sh",
        ROOT / "operations/scripts/rollback.sh",
        ROOT / "operations/scripts/transition-lock.sh",
    ):
        subprocess.run(["bash", "-n", str(script)], check=True)


TRANSITION_ENTRYPOINTS = (
    "deploy-shadow.sh",
    "cutover-preflight.sh",
    "switch-routing.sh",
    "writer-cutover.sh",
    "rollback.sh",
)


def test_transition_lock_is_fixed_hardened_and_held_before_shared_work() -> None:
    script_dir = ROOT / "operations/scripts"
    helper = (script_dir / "transition-lock.sh").read_text(encoding="utf-8")
    scripts = {
        name: (script_dir / name).read_text(encoding="utf-8")
        for name in TRANSITION_ENTRYPOINTS
    }

    assert "readonly MRANKED_TRANSITION_LOCK_PATH=/run/lock/m-ranked-transition.lock" in helper
    assert "readonly MRANKED_TRANSITION_LOCK_DESCRIPTOR=8" in helper
    assert "readonly MRANKED_TRANSITION_FLOCK_BIN=/usr/bin/flock" in helper
    assert "transition lock is not provisioned" in helper
    assert 'chmod 0600 "$lock_path"' not in helper
    assert 'chown root:root "$lock_path"' not in helper
    assert 'rm -f -- "$lock_path"' not in helper
    assert 'export MRANKED_TRANSITION_LOCK_FD="$MRANKED_TRANSITION_LOCK_DESCRIPTOR"' in helper
    assert "MRANKED_TRANSITION_LOCK_PATH:=" not in helper
    assert "emergency" not in helper.lower()
    assert "operations/scripts/transition-lock.sh" in scripts["deploy-shadow.sh"]
    assert "operations/tmpfiles.d/m-ranked-transition.conf" in scripts["deploy-shadow.sh"]
    assert '"${MRANKED_INSTALL_ROOT:-}" != /opt/m-ranked/releases' in helper
    assert '"${MRANKED_CURRENT_LINK:-}" != /opt/m-ranked/current' in helper
    assert helper.count("_mranked_transition_secure_directory_chain") >= 5

    for name, script in scripts.items():
        assert script.startswith("#!/bin/bash -p\nset -Eeuo pipefail\n")
        fixed_path = script.index("PATH=/usr/bin:/bin:/usr/sbin:/sbin")
        scrub = script.index(
            "unset BASH_ENV CDPATH ENV PYTHONHOME PYTHONPATH TMPDIR __PYVENV_LAUNCHER__"
        )
        pre_source_check = script.index('transition_helper_identity="$(_mranked_bootstrap_stat')
        source = script.index('source "$transition_lock_helper"')
        acquire = script.index("mranked_transition_lock_acquire")
        assert fixed_path < scrub < pre_source_check < source < acquire
        assert '"$transition_owner" != 0' in script[:source]
        assert "8#022" in script[:source]
        assert '"$transition_links" != 1' in script[:source]

    deploy = scripts["deploy-shadow.sh"]
    preflight = scripts["cutover-preflight.sh"]
    switch = scripts["switch-routing.sh"]
    writer = scripts["writer-cutover.sh"]
    rollback = scripts["rollback.sh"]
    assert deploy.index("mranked_transition_lock_acquire") < deploy.index(
        "validate_deploy_namespace"
    )
    assert preflight.index("mranked_transition_lock_acquire") < preflight.index(
        "for command_name in curl jq psql"
    )
    assert switch.index("mranked_transition_lock_acquire") < switch.index(
        '"$preflight" --mode'
    )
    assert switch.index("mranked_transition_lock_acquire") < switch.index(
        'exec 9>"$NGINX_ROUTE_LOCK"'
    )
    assert writer.index("mranked_transition_lock_acquire") < writer.index(
        'if [[ ! -f "$LEGACY_SQLITE_PATH"'
    )
    assert writer.index("mranked_transition_lock_acquire") < writer.index(
        '"$preflight" --mode writer-cutover'
    )
    assert rollback.index("mranked_transition_lock_acquire") < rollback.index(
        '"$route_switch" --phase legacy'
    )
    for name in (
        "cutover-preflight.sh",
        "switch-routing.sh",
        "writer-cutover.sh",
        "rollback.sh",
    ):
        assert "mranked_transition_require_active_entrypoint" in scripts[name]
    assert (
        '"$REVERSE_SYNC_EXECUTABLE" operations/bin/pg-to-legacy-sync true'
        in writer
    )
    assert (
        '"$REVERSE_SYNC_EXECUTABLE" operations/bin/pg-to-legacy-sync true'
        in rollback
    )


def _write_flock_compatibility_shim(path: Path) -> None:
    path.write_text(
        f"#!{sys.executable}\n"
        "import errno\n"
        "import fcntl\n"
        "import sys\n"
        "if sys.argv[1:3] != ['-n', '-x']:\n"
        "    raise SystemExit(64)\n"
        "try:\n"
        "    fcntl.flock(int(sys.argv[3]), fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "except OSError as exc:\n"
        "    if exc.errno in (errno.EACCES, errno.EAGAIN):\n"
        "        raise SystemExit(1)\n"
        "    raise\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _lock_harness_command() -> str:
    return """
set -Eeuo pipefail
source "$1"
_mranked_transition_lock_acquire "$2" "$3" "$4" "$5" "$6"
"""


def test_transition_lock_serializes_reuses_fd8_and_rejects_forgery(
    tmp_path: Path,
) -> None:
    helper = (ROOT / "operations/scripts/transition-lock.sh").resolve()
    lock_dir = (tmp_path / "lock-dir").resolve()
    lock_dir.mkdir(mode=0o700)
    lock_path = lock_dir / "transition.lock"
    lock_path.write_bytes(b"")
    lock_path.chmod(0o600)
    flock_shim = lock_dir / "flock-shim"
    _write_flock_compatibility_shim(flock_shim)
    uid = str(os.geteuid())
    identity_mode = "darwin-test" if sys.platform == "darwin" else "strict"
    nested_marker = tmp_path / "nested-acquired"
    holder_command = """
set -Eeuo pipefail
source "$1"
_mranked_transition_lock_acquire "$2" "$3" "$4" "$5" "$6"
/bin/bash -p -c '
  set -Eeuo pipefail
  source "$1"
  _mranked_transition_lock_acquire "$2" "$3" "$4" "$5" "$6"
' transition-lock-nested "$1" "$2" "$3" "$4" "$5" "$6"
printf nested-ok >"$7"
IFS= read -r _
"""
    clean_env = os.environ.copy()
    clean_env.pop("MRANKED_TRANSITION_LOCK_FD", None)
    holder = subprocess.Popen(
        [
            "/bin/bash",
            "-p",
            "-c",
            holder_command,
            "transition-lock-holder",
            str(helper),
            str(lock_path),
            str(flock_shim),
            uid,
            identity_mode,
            str(lock_dir),
            str(nested_marker),
        ],
        env=clean_env,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not nested_marker.exists():
            if holder.poll() is not None:
                break
            time.sleep(0.02)
        if not nested_marker.exists():
            holder_status = holder.poll()
            holder_error = "holder remained blocked"
            if holder_status is not None and holder.stderr is not None:
                holder_error = holder.stderr.read()
            raise AssertionError(
                f"nested lock reuse failed status={holder_status}: {holder_error}"
            )
        assert nested_marker.read_text(encoding="utf-8") == "nested-ok"

        contender = subprocess.run(
            [
                "/bin/bash",
                "-p",
                "-c",
                _lock_harness_command(),
                "transition-lock-contender",
                str(helper),
                str(lock_path),
                str(flock_shim),
                uid,
                identity_mode,
                str(lock_dir),
            ],
            env=clean_env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert contender.returncode == 75
        assert "transition is in progress" in contender.stderr

        forged = subprocess.run(
            [
                "/bin/bash",
                "-p",
                "-c",
                'exec 8</dev/null\nexport MRANKED_TRANSITION_LOCK_FD=8\n'
                + _lock_harness_command(),
                "transition-lock-forged",
                str(helper),
                str(lock_path),
                str(flock_shim),
                uid,
                identity_mode,
                str(lock_dir),
            ],
            env=clean_env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert forged.returncode == 75
        assert "descriptor is invalid" in forged.stderr
    finally:
        if holder.poll() is None and holder.stdin is not None:
            holder.stdin.write("release\n")
            holder.stdin.flush()
        holder.communicate(timeout=5)

    reacquired = subprocess.run(
        [
            "/bin/bash",
            "-p",
            "-c",
            _lock_harness_command(),
            "transition-lock-reacquire",
            str(helper),
            str(lock_path),
            str(flock_shim),
            uid,
            identity_mode,
            str(lock_dir),
        ],
        env=clean_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert reacquired.returncode == 0, reacquired.stderr

    if os.geteuid() != 0:
        lock_path.chmod(0o000)
        unreadable = subprocess.run(
            [
                "/bin/bash",
                "-p",
                "-c",
                _lock_harness_command(),
                "transition-lock-unreadable",
                str(helper),
                str(lock_path),
                str(flock_shim),
                uid,
                identity_mode,
                str(lock_dir),
            ],
            env=clean_env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert unreadable.returncode == 73


def test_transition_lock_never_creates_or_repairs_an_untrusted_path(
    tmp_path: Path,
) -> None:
    helper = (ROOT / "operations/scripts/transition-lock.sh").resolve()
    lock_dir = (tmp_path / "lock-dir").resolve()
    lock_dir.mkdir(mode=0o700)
    flock_shim = lock_dir / "flock-shim"
    _write_flock_compatibility_shim(flock_shim)
    uid = str(os.geteuid())
    identity_mode = "darwin-test" if sys.platform == "darwin" else "strict"
    clean_env = os.environ.copy()
    clean_env.pop("MRANKED_TRANSITION_LOCK_FD", None)

    absent_lock = lock_dir / "absent.lock"
    absent = subprocess.run(
        [
            "/bin/bash",
            "-p",
            "-c",
            _lock_harness_command(),
            "transition-lock-absent",
            str(helper),
            str(absent_lock),
            str(flock_shim),
            uid,
            identity_mode,
            str(lock_dir),
        ],
        env=clean_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert absent.returncode == 73
    assert "not provisioned" in absent.stderr
    assert not absent_lock.exists()

    victim = lock_dir / "victim"
    victim.write_text("must-not-change\n", encoding="utf-8")
    victim.chmod(0o666)
    malicious_lock = lock_dir / "symlink.lock"
    malicious_lock.symlink_to(victim)
    before_mode = victim.stat().st_mode & 0o777
    symlinked = subprocess.run(
        [
            "/bin/bash",
            "-p",
            "-c",
            _lock_harness_command(),
            "transition-lock-symlink",
            str(helper),
            str(malicious_lock),
            str(flock_shim),
            uid,
            identity_mode,
            str(lock_dir),
        ],
        env=clean_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert symlinked.returncode == 73
    assert victim.read_text(encoding="utf-8") == "must-not-change\n"
    assert victim.stat().st_mode & 0o777 == before_mode
    assert malicious_lock.is_symlink()

    secure_root = tmp_path / "ancestor-root"
    secure_root.mkdir(mode=0o700)
    writable_ancestor = secure_root / "writable"
    writable_ancestor.mkdir(mode=0o777)
    writable_ancestor.chmod(0o777)
    nested_lock_dir = writable_ancestor / "lock-dir"
    nested_lock_dir.mkdir(mode=0o700)
    nested_lock = nested_lock_dir / "transition.lock"
    nested_lock.write_bytes(b"")
    nested_lock.chmod(0o600)
    nested_flock = nested_lock_dir / "flock-shim"
    _write_flock_compatibility_shim(nested_flock)
    unsafe_ancestor = subprocess.run(
        [
            "/bin/bash",
            "-p",
            "-c",
            _lock_harness_command(),
            "transition-lock-ancestor",
            str(helper),
            str(nested_lock),
            str(nested_flock),
            uid,
            identity_mode,
            str(secure_root),
        ],
        env=clean_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert unsafe_ancestor.returncode == 73
    assert "parent is unsafe" in unsafe_ancestor.stderr


def test_secure_directory_chain_rejects_aliases_writable_dirs_and_replacement(
    tmp_path: Path,
) -> None:
    helper = (ROOT / "operations/scripts/transition-lock.sh").resolve()
    secure_root = (tmp_path / "secure-root").resolve()
    secure_root.mkdir(mode=0o700)
    child = secure_root / "child"
    child.mkdir(mode=0o700)
    uid = str(os.geteuid())
    harness = """
set -Eeuo pipefail
source "$1"
_mranked_transition_secure_directory_chain "$2" "$4" "$3"
_mranked_transition_directory_chain_identity "$2" "$4" "$3"
"""

    def run(path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "/bin/bash",
                "-p",
                "-c",
                harness,
                "secure-chain-test",
                str(helper),
                str(path),
                str(secure_root),
                uid,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    accepted = run(child)
    assert accepted.returncode == 0, accepted.stderr
    original_identity = accepted.stdout

    alias = secure_root / "alias"
    alias.symlink_to(child, target_is_directory=True)
    assert run(alias).returncode != 0

    child.chmod(0o720)
    assert run(child).returncode != 0
    child.chmod(0o700)
    moved = secure_root / "moved"
    child.rename(moved)
    child.mkdir(mode=0o700)
    replaced = run(child)
    assert replaced.returncode == 0, replaced.stderr
    assert replaced.stdout != original_identity


def test_deploy_namespace_and_artifact_source_are_exactly_bound(
    tmp_path: Path,
) -> None:
    deploy = (ROOT / "operations/scripts/deploy-shadow.sh").read_text(
        encoding="utf-8"
    )
    namespace_function = _shell_function(deploy, "validate_deploy_namespace")
    namespace_harness = f"""
set -Eeuo pipefail
_mranked_transition_secure_directory_chain() {{ :; }}
{namespace_function}
MRANKED_INSTALL_ROOT="$1"
MRANKED_CURRENT_LINK="$2"
DEPLOY_REPORT_DIR="$3"
validate_deploy_namespace
"""

    def namespace_result(
        install_root: str, current_link: str, report_dir: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "/bin/bash",
                "-c",
                namespace_harness,
                "deploy-namespace-test",
                install_root,
                current_link,
                report_dir,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    assert namespace_result(
        "/opt/m-ranked/releases",
        "/opt/m-ranked/current",
        "/var/lib/m-ranked/deploy-reports",
    ).returncode == 0
    for invalid in (
        ("/opt/m-ranked/../m-ranked/releases", "/opt/m-ranked/current", "/var/lib/m-ranked/deploy-reports"),
        ("/opt/m-ranked/releases/", "/opt/m-ranked/current", "/var/lib/m-ranked/deploy-reports"),
        ("/srv/m-ranked/releases", "/srv/m-ranked/current", "/var/lib/m-ranked/deploy-reports"),
        ("/srv/m-ranked/releases", "/opt/m-ranked/current", "/var/lib/m-ranked/deploy-reports"),
        ("/opt/m-ranked/releases", "/opt/m-ranked/./current", "/var/lib/m-ranked/deploy-reports"),
        ("/opt/m-ranked/releases", "/opt/m-ranked/current", "/var/lib/m-ranked/../m-ranked/deploy-reports"),
    ):
        assert namespace_result(*invalid).returncode != 0, invalid

    artifact = (tmp_path / "release-1").resolve()
    script_dir = artifact / "operations/scripts"
    script_dir.mkdir(parents=True)
    entrypoint = script_dir / "deploy-shadow.sh"
    entrypoint.write_text("#!/bin/bash -p\n", encoding="utf-8")
    other = (tmp_path / "other-release").resolve()
    other.mkdir()
    alias = tmp_path / "release-alias"
    alias.symlink_to(artifact, target_is_directory=True)
    bind_function = _shell_function(deploy, "bind_release_source_to_entrypoint")
    bind_harness = f"""
set -Eeuo pipefail
{bind_function}
transition_entry_dir="$1"
transition_entry_path="$2"
release_id="$3"
release_source="$4"
bind_release_source_to_entrypoint "$release_source"
printf '%s\n' "$release_source"
"""

    def bind_result(
        source: str, *, entry: Path = entrypoint, release_id: str = "release-1"
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "/bin/bash",
                "-c",
                bind_harness,
                "deploy-source-binding-test",
                str(entry.parent),
                str(entry),
                release_id,
                source,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    accepted = bind_result(str(artifact))
    assert accepted.returncode == 0, accepted.stderr
    assert accepted.stdout.strip() == str(artifact)
    assert bind_result(f"{artifact}/.").returncode != 0
    assert bind_result(str(alias)).returncode != 0
    assert bind_result(str(other)).returncode != 0
    assert bind_result(str(artifact), release_id="wrong-id").returncode != 0
    assert bind_result(str(artifact), entry=script_dir / "other.sh").returncode != 0


def test_release_tree_trust_and_executable_cohort_fail_closed(
    tmp_path: Path,
) -> None:
    deploy = (ROOT / "operations/scripts/deploy-shadow.sh").read_text(
        encoding="utf-8"
    )
    trust_function = _shell_function(deploy, "validate_release_tree_trust")
    cohort_function = _shell_function(deploy, "validate_executable_cohort")
    helper = (ROOT / "operations/scripts/transition-lock.sh").resolve()
    release = tmp_path / "release"
    (release / ".venv/bin").mkdir(parents=True)
    for name in ("one", "two", ".venv/bin/python"):
        path = release / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    uid = str(os.geteuid())
    harness = f"""
set -Eeuo pipefail
source "$1"
executable_files=(one two)
{trust_function}
{cohort_function}
validate_release_tree_trust "$2" "$3"
validate_executable_cohort "$2" installed "$3"
"""

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "/bin/bash",
                "-p",
                "-c",
                harness,
                "release-trust-test",
                str(helper),
                str(release),
                uid,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    accepted = run()
    assert accepted.returncode == 0, accepted.stderr
    (release / "two").unlink()
    assert run().returncode != 0
    (release / "two").write_text("#!/bin/sh\n", encoding="utf-8")
    (release / "two").chmod(0o755)
    hardlink = release / "hardlink"
    os.link(release / "one", hardlink)
    hardlinked = run()
    assert hardlinked.returncode != 0
    assert "hard-linked" in hardlinked.stderr
    hardlink.unlink()
    python = release / ".venv/bin/python"
    python.unlink()
    python.mkdir()
    assert run().returncode != 0
    python.rmdir()
    interpreter_directory = release / ".venv/bin/interpreter-directory"
    interpreter_directory.mkdir()
    python.symlink_to(interpreter_directory, target_is_directory=True)
    assert run().returncode != 0


def test_transition_lock_boot_provisioning_and_fail_fast_operator_shells(
    tmp_path: Path,
) -> None:
    tmpfiles = ROOT / "operations/tmpfiles.d/m-ranked-transition.conf"
    records = [
        line
        for line in tmpfiles.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert records == ["f /run/lock/m-ranked-transition.lock 0600 root root -"]
    deploy = (ROOT / "operations/scripts/deploy-shadow.sh").read_text(
        encoding="utf-8"
    )
    deploy_docs = (ROOT / "operations/runbooks/DEPLOY.md").read_text(
        encoding="utf-8"
    )
    assert "operations/tmpfiles.d/m-ranked-transition.conf" in deploy
    assert "systemd-tmpfiles --create /etc/tmpfiles.d/m-ranked-transition.conf" in deploy_docs
    assert "chown -hR" not in deploy_docs
    assert 'unsafe_owner="$(find ' in deploy_docs
    assert 'unsafe_mode="$(find ' in deploy_docs
    assert 'unsafe_hardlink="$(find ' in deploy_docs

    wrapper_marker = "rtk sudo /bin/bash -p -c '"
    wrappers = []
    for relative_path in (
        "operations/runbooks/DEPLOY.md",
        "operations/runbooks/CUTOVER.md",
        "operations/runbooks/ROLLBACK.md",
    ):
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        wrappers.extend(text.split(wrapper_marker)[1:])
    assert len(wrappers) == 6
    for wrapper in wrappers:
        body = wrapper.split("\n'", 1)[0]
        assert body.startswith("\n  set -Eeuo pipefail\n  PATH=/usr/bin:/bin:/usr/sbin:/sbin\n")
        if "source /etc/m-ranked/cutover.env" in body:
            assert body.index("set -Eeuo pipefail") < body.index(
                "source /etc/m-ranked/cutover.env"
            )
            assert body.index("source /etc/m-ranked/cutover.env") < body.index("exec ")

    failing_env = tmp_path / "cutover.env"
    failing_env.write_text(
        "OPERATOR_ID=partial-operator\n"
        "CHANGE_TICKET=partial-ticket\n"
        "return 23\n",
        encoding="utf-8",
    )
    marker = tmp_path / "entrypoint-executed"
    entrypoint = tmp_path / "entrypoint"
    entrypoint.write_text(
        f"#!/bin/bash -p\nprintf executed > {marker!s}\n",
        encoding="utf-8",
    )
    entrypoint.chmod(0o755)
    result = subprocess.run(
        [
            "/bin/bash",
            "-p",
            "-c",
            "set -Eeuo pipefail\n"
            "PATH=/usr/bin:/bin:/usr/sbin:/sbin\n"
            "set -a; source \"$1\"; set +a\n"
            "exec \"$2\"",
            "fail-fast-doc-wrapper-test",
            str(failing_env),
            str(entrypoint),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 23
    assert not marker.exists()


def _make_origin_fixture(release: Path, helper_source: Path) -> Path:
    script_dir = release / "operations/scripts"
    script_dir.mkdir(parents=True)
    helper = script_dir / "transition-lock.sh"
    helper.write_bytes(helper_source.read_bytes())
    helper.chmod(0o644)
    entry = script_dir / "switch-routing.sh"
    entry.write_text("#!/bin/bash -p\nexit 0\n", encoding="utf-8")
    entry.chmod(0o755)
    sibling = script_dir / "cutover-preflight.sh"
    sibling.write_text("#!/bin/bash -p\nexit 0\n", encoding="utf-8")
    sibling.chmod(0o755)
    return entry


def test_active_origin_rejects_stale_copy_and_accepts_only_same_release_sibling(
    tmp_path: Path,
) -> None:
    helper_source = ROOT / "operations/scripts/transition-lock.sh"
    install_root = tmp_path / "m-ranked/releases"
    active = install_root / "active-release"
    stale = install_root / "stale-release"
    active_entry = _make_origin_fixture(active, helper_source)
    stale_entry = _make_origin_fixture(stale, helper_source)
    current_link = tmp_path / "m-ranked/current"
    current_link.symlink_to(active.resolve(), target_is_directory=True)
    uid = str(os.geteuid())
    harness = """
set -Eeuo pipefail
source "$1"
MRANKED_CURRENT_LINK="$4"
_mranked_transition_require_active_entrypoint "$2" "$3" "$4" "$5"
_mranked_transition_require_active_file \
  "$6" operations/scripts/cutover-preflight.sh true "$5"
"""

    active_result = subprocess.run(
        [
            "/bin/bash",
            "-p",
            "-c",
            harness,
            "active-origin-test",
            str(active / "operations/scripts/transition-lock.sh"),
            str(active_entry),
            str(install_root),
            str(current_link),
            uid,
            str(active / "operations/scripts/cutover-preflight.sh"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert active_result.returncode == 0, active_result.stderr

    stale_result = subprocess.run(
        [
            "/bin/bash",
            "-p",
            "-c",
            harness,
            "stale-origin-test",
            str(stale / "operations/scripts/transition-lock.sh"),
            str(stale_entry),
            str(install_root),
            str(current_link),
            uid,
            str(stale / "operations/scripts/cutover-preflight.sh"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert stale_result.returncode != 0


def test_privileged_entrypoints_ignore_hostile_shell_environment_and_helper(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "environment-executed"
    bash_env = tmp_path / "BASH_ENV"
    bash_env.write_text(f"printf env > {marker}\n", encoding="utf-8")
    hostile_bin = tmp_path / "bin"
    hostile_bin.mkdir()
    helper_marker = tmp_path / "writable-helper-executed"

    env = os.environ.copy()
    env.update({"BASH_ENV": str(bash_env), "PATH": str(hostile_bin)})
    for name in TRANSITION_ENTRYPOINTS:
        source = ROOT / "operations/scripts" / name
        copied_dir = tmp_path / name.removesuffix(".sh") / "operations/scripts"
        copied_dir.mkdir(parents=True)
        copied_entry = copied_dir / name
        copied_entry.write_bytes(source.read_bytes())
        copied_entry.chmod(0o755)
        copied_helper = copied_dir / "transition-lock.sh"
        copied_helper.write_text(
            f"printf helper > {helper_marker}\n",
            encoding="utf-8",
        )
        copied_helper.chmod(0o666)
        result = subprocess.run(
            [str(copied_entry), "--definitely-invalid"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0
        assert not marker.exists(), name
        assert not helper_marker.exists(), name
