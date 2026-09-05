from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any, Iterable, Mapping, Sequence
from uuid import UUID


REPORT_TYPE = "collector-parity-rehearsal"
REPORT_VERSION = 1
SOURCE_TYPE = "collector-parity-shadow-observations"
SOURCE_VERSION = 1
DEFAULT_MAX_AGE_SECONDS = 86_400
CLOCK_SKEW_SECONDS = 5
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_RAW_EVIDENCE_BYTES = 64 * 1024 * 1024
MAX_RELEASE_FILE_BYTES = 256 * 1024 * 1024
MAX_RELEASE_TREE_BYTES = 4 * 1024 * 1024 * 1024

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

PLATFORMS = ("max", "rutube", "telegram", "vk")
PROJECTIONS = (
    "comparison",
    "institution_daily_metrics",
    "institution_monthly_metrics",
    "institution_period_metrics",
    "publication_hourly",
    "publication_latest",
)
AUTHORITATIVE_MISSING_REASONS = {
    "telegram": {
        "telegram_mtproto_empty_get_messages",
        "telegram_public_deleted_marker",
        "telegram_public_http_404",
        "telegram_public_http_410",
    },
    "vk": {"vk_wall_get_by_id_not_found_or_deleted"},
    "max": {"max_get_messages_not_found_or_deleted"},
    "rutube": {"rutube_video_http_404", "rutube_video_http_410"},
}
PROVIDER_MODES = {
    "telegram": {"mtproto", "public-web"},
    "vk": {"vk-api"},
    "max": {"max-api"},
    "rutube": {"rutube-api"},
}
EXPECTED_POLICY = {
    "deletionConfirmationChecks": 2,
    "refreshLimit": 100,
    "refreshScanLimit": 400,
    "trackPostForHours": 960,
}

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:+/-]{1,127}$")
SAFE_NAMESPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,79}$")
SAFE_DATABASE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SYMLINK_PATH_RE = re.compile(r"^[A-Za-z0-9._+@%/-]+$")
SYMLINK_TARGET_RE = re.compile(r"^[-A-Za-z0-9._+@%/=:,~]+$")
PLACEHOLDER_RE = re.compile(
    r"(?:replace[-_ ]?with|change[-_ ]?me|placeholder|example|todo|tbd)",
    re.IGNORECASE,
)
NON_ACCEPTANCE_DATABASE_RE = re.compile(
    r"(?:^|[_.-])(local|unit|fixture|test|testing|dev|demo|disposable)(?:$|[_.-])",
    re.IGNORECASE,
)


class EvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class FileSnapshot:
    data: bytes
    digest: str
    device: int
    inode: int
    mode: int
    links: int
    size: int
    mtime_ns: int
    ctime_ns: int

    @classmethod
    def from_read(
        cls, data: bytes, digest: str, metadata: os.stat_result
    ) -> "FileSnapshot":
        return cls(
            data=data,
            digest=digest,
            device=metadata.st_dev,
            inode=metadata.st_ino,
            mode=metadata.st_mode,
            links=metadata.st_nlink,
            size=metadata.st_size,
            mtime_ns=metadata.st_mtime_ns,
            ctime_ns=metadata.st_ctime_ns,
        )

    def same_file(self, metadata: os.stat_result) -> bool:
        return (
            self.device,
            self.inode,
            self.mode,
            self.links,
            self.size,
            self.mtime_ns,
            self.ctime_ns,
        ) == (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )


def _fail(message: str) -> None:
    raise EvidenceError(message)


def _object(value: Any, label: str, keys: Iterable[str]) -> Mapping[str, Any]:
    expected = set(keys)
    if not isinstance(value, dict) or set(value) != expected:
        _fail(f"{label} must be an object with exactly: {', '.join(sorted(expected))}")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(f"{label} must be an array")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{label} must be a nonempty string")
    return value


def _integer(value: Any, label: str, minimum: int | None = 0) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        suffix = "" if minimum is None else f" >= {minimum}"
        _fail(f"{label} must be an integer{suffix}")
    return value


def _zero(value: Any, label: str) -> None:
    if type(value) is not int or value != 0:
        _fail(f"{label} must be integer zero")


def _true(value: Any, label: str) -> None:
    if value is not True:
        _fail(f"{label} must be true")


def _false(value: Any, label: str) -> None:
    if value is not False:
        _fail(f"{label} must be false")


def _sha256(value: Any, label: str) -> str:
    text = _string(value, label)
    if not SHA256_RE.fullmatch(text):
        _fail(f"{label} must be a lowercase SHA-256")
    return text


def _identity(value: Any, label: str) -> str:
    text = _string(value, label)
    if not SAFE_ID_RE.fullmatch(text) or PLACEHOLDER_RE.search(text):
        _fail(f"{label} is unsafe or a placeholder")
    return text


def _source_namespace(value: Any, label: str) -> str:
    text = _string(value, label)
    if (
        not SAFE_NAMESPACE_RE.fullmatch(text)
        or PLACEHOLDER_RE.search(text)
        or NON_ACCEPTANCE_DATABASE_RE.search(text)
    ):
        _fail(f"{label} identifies a local/test namespace")
    return text


def _uuid(value: Any, label: str) -> str:
    text = _string(value, label)
    try:
        parsed = UUID(text)
    except ValueError:
        _fail(f"{label} must be a canonical UUID")
    if str(parsed) != text or parsed.variant != "specified in RFC 4122":
        _fail(f"{label} must be a lowercase canonical RFC 4122 UUID")
    return text


def _timestamp(value: Any, label: str) -> datetime:
    text = _string(value, label)
    if not UTC_TIMESTAMP_RE.fullmatch(text):
        _fail(f"{label} must be UTC with second precision and a Z suffix")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        _fail(f"{label} is not a valid UTC timestamp")
    return parsed


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _age_is_valid(
    value: datetime, now: datetime, max_age_seconds: int, label: str
) -> None:
    age = (now - value).total_seconds()
    if age < -CLOCK_SKEW_SECONDS or age > max_age_seconds:
        _fail(f"{label} is future-dated or older than {max_age_seconds} seconds")


def _json_no_duplicates(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _regular_file(path: Path, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as error:
        _fail(f"{label} is unavailable: {error.__class__.__name__}")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        _fail(f"{label} must be a regular non-symlink file")
    return metadata


def _safe_relative_parts(path: Path, root: Path, label: str) -> tuple[str, ...]:
    if not path.is_absolute() or not root.is_absolute():
        _fail(f"{label} and its confinement root must be absolute")
    try:
        relative = path.relative_to(root)
    except ValueError:
        _fail(f"{label} must be lexically below its confinement root")
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        _fail(f"{label} contains an unsafe path component")
    return relative.parts


def _open_directory_chain(path: Path, label: str) -> int:
    if not path.is_absolute():
        _fail(f"{label} must be absolute")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    if not nofollow or not directory_flag:
        _fail("this platform cannot enforce safe directory traversal")
    flags = os.O_RDONLY | directory_flag | nofollow | getattr(os, "O_CLOEXEC", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open("/", flags)
        for component in path.parts[1:]:
            if component in {"", ".", ".."}:
                _fail(f"{label} contains an unsafe path component")
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except EvidenceError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except OSError as error:
        if descriptor is not None:
            os.close(descriptor)
        _fail(f"{label} cannot be traversed safely: {error.__class__.__name__}")


def _open_parent_directory(
    path: Path, label: str, confinement_root: Path | None = None
) -> tuple[int, str]:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        _fail(f"{label} must be an absolute file path")
    if confinement_root is None:
        return _open_directory_chain(path.parent, f"{label} parent"), path.name
    relative_parts = _safe_relative_parts(path, confinement_root, label)
    descriptor = _open_directory_chain(confinement_root, f"{label} confinement root")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    flags = os.O_RDONLY | directory_flag | nofollow | getattr(os, "O_CLOEXEC", 0)
    try:
        for component in relative_parts[:-1]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor, relative_parts[-1]
    except OSError as error:
        os.close(descriptor)
        _fail(f"{label} cannot be traversed below its confinement root: {error.__class__.__name__}")


def _read_stable_file(
    path: Path,
    label: str,
    *,
    maximum_bytes: int,
    minimum_bytes: int = 1,
    confinement_root: Path | None = None,
    capture_data: bool = True,
) -> FileSnapshot:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        _fail("this platform cannot enforce O_NOFOLLOW")
    descriptor: int | None = None
    parent_descriptor: int | None = None
    try:
        parent_descriptor, basename = _open_parent_directory(
            path, label, confinement_root
        )
        descriptor = os.open(
            basename,
            os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_descriptor,
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            _fail(f"{label} must be a regular non-symlink file")
        if not minimum_bytes <= before.st_size <= maximum_bytes:
            _fail(f"{label} size is outside the accepted range")
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                _fail(f"{label} changed while being read")
            if capture_data:
                chunks.append(chunk)
            digest.update(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            _fail(f"{label} grew while being read")
        after = os.fstat(descriptor)
        snapshot = FileSnapshot.from_read(
            b"".join(chunks) if capture_data else b"",
            digest.hexdigest(),
            after,
        )
        if not FileSnapshot.from_read(b"", "", before).same_file(after):
            _fail(f"{label} changed while being read")
    except EvidenceError:
        raise
    except OSError as error:
        _fail(f"{label} cannot be opened safely: {error.__class__.__name__}")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)
    _recheck_snapshot_path(path, snapshot, label)
    return snapshot


def _recheck_snapshot_path(path: Path, snapshot: FileSnapshot, label: str) -> None:
    try:
        current = path.lstat()
    except OSError as error:
        _fail(f"{label} disappeared after read: {error.__class__.__name__}")
    if stat.S_ISLNK(current.st_mode) or not snapshot.same_file(current):
        _fail(f"{label} was replaced during validation")


def _decode_json(snapshot: FileSnapshot, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(
            snapshot.data.decode("utf-8"), object_pairs_hook=_json_no_duplicates
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        _fail(f"{label} is not valid UTF-8 JSON: {error.__class__.__name__}")
    if not isinstance(value, dict):
        _fail(f"{label} must contain one JSON object")
    return value


def _load_json_snapshot(
    path: Path, label: str, *, confinement_root: Path | None = None
) -> tuple[Mapping[str, Any], FileSnapshot]:
    snapshot = _read_stable_file(
        path,
        label,
        maximum_bytes=MAX_JSON_BYTES,
        confinement_root=confinement_root,
    )
    return _decode_json(snapshot, label), snapshot


def _load_json(path: Path, label: str) -> Mapping[str, Any]:
    return _load_json_snapshot(path, label)[0]


def _hash_file(path: Path) -> str:
    return _read_stable_file(
        path,
        "file",
        maximum_bytes=MAX_RELEASE_FILE_BYTES,
        minimum_bytes=0,
        capture_data=False,
    ).digest


def _real_directory(path: Path, label: str) -> Path:
    if not path.is_absolute():
        _fail(f"{label} must be absolute")
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        _fail(f"{label} is unavailable: {error.__class__.__name__}")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        _fail(f"{label} must be a real non-symlink directory")
    if resolved != path:
        _fail(f"{label} must use its canonical path without symlink ancestors")
    return resolved


def _within(path: Path, root: Path, label: str) -> Path:
    if not path.is_absolute():
        _fail(f"{label} must be absolute")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        _fail(f"{label} must resolve below the evidence root")
    if resolved != path:
        _fail(f"{label} must not traverse a symlink or alias")
    return resolved


def _load_checksummed_json(
    report_path: Path,
    label: str,
    *,
    basename_only: bool,
    confinement_root: Path | None = None,
) -> tuple[Mapping[str, Any], FileSnapshot, FileSnapshot]:
    sidecar = Path(f"{report_path}.sha256")
    report, report_snapshot = _load_json_snapshot(
        report_path, label, confinement_root=confinement_root
    )
    sidecar_snapshot = _read_stable_file(
        sidecar,
        f"{label} SHA-256 sidecar",
        maximum_bytes=4096,
        confinement_root=confinement_root,
    )
    try:
        record = sidecar_snapshot.data.decode("ascii")
    except UnicodeError:
        _fail(f"{label} SHA-256 sidecar is not ASCII")
    separator = r"  " if basename_only else r"[ \t]+"
    match = re.fullmatch(rf"([0-9a-f]{{64}}){separator}([^\n]+)\n", record)
    if not match:
        _fail(f"{label} SHA-256 sidecar is malformed")
    named_path = match.group(2).removeprefix("*")
    accepted_names = {report_path.name} if basename_only else {report_path.name, str(report_path)}
    if named_path not in accepted_names:
        _fail(f"{label} SHA-256 sidecar names another file")
    if match.group(1) != report_snapshot.digest:
        _fail(f"{label} SHA-256 does not match")
    _recheck_snapshot_path(report_path, report_snapshot, label)
    _recheck_snapshot_path(sidecar, sidecar_snapshot, f"{label} SHA-256 sidecar")
    return report, report_snapshot, sidecar_snapshot


def _read_stable_symlink(
    path: Path, release_path: Path, label: str
) -> tuple[bytes, os.stat_result]:
    parent_descriptor: int | None = None
    try:
        parent_descriptor, basename = _open_parent_directory(
            path, label, release_path
        )
        basename_bytes = os.fsencode(basename)
        before = os.stat(
            basename_bytes, dir_fd=parent_descriptor, follow_symlinks=False
        )
        if not stat.S_ISLNK(before.st_mode):
            _fail(f"{label} is not a symlink")
        raw_target = os.readlink(basename_bytes, dir_fd=parent_descriptor)
        after = os.stat(
            basename_bytes, dir_fd=parent_descriptor, follow_symlinks=False
        )
        if not FileSnapshot.from_read(b"", "", before).same_file(after):
            _fail(f"{label} changed while being read")
    except EvidenceError:
        raise
    except OSError as error:
        _fail(f"{label} cannot be read safely: {error.__class__.__name__}")
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)
    return raw_target, after


def _parse_symlink_manifest(release_path: Path) -> dict[str, str]:
    path = release_path / "SYMLINKS.sha256"
    snapshot = _read_stable_file(
        path,
        "active release SYMLINKS.sha256",
        maximum_bytes=16 * 1024 * 1024,
        minimum_bytes=0,
        confinement_root=release_path,
    )
    data = snapshot.data
    if data and not data.endswith(b"\n"):
        _fail("active release SYMLINKS.sha256 must end with a newline")
    records = data.splitlines(keepends=True)
    if records != sorted(records):
        _fail("active release SYMLINKS.sha256 must be bytewise sorted")
    result: dict[str, str] = {}
    for record in records:
        try:
            text = record.decode("ascii")
        except UnicodeError:
            _fail("active release SYMLINKS.sha256 must be ASCII")
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._+@%/-]+)\n", text)
        if not match:
            _fail("active release SYMLINKS.sha256 contains a malformed record")
        target_sha256, relative_name = match.groups()
        pure_path = PurePosixPath(relative_name)
        if (
            not SYMLINK_PATH_RE.fullmatch(relative_name)
            or pure_path.is_absolute()
            or relative_name in result
            or any(part in {"", ".", ".."} for part in pure_path.parts)
        ):
            _fail("active release SYMLINKS.sha256 contains an unsafe or duplicate path")
        result[relative_name] = target_sha256
    return result


def _resolved_symlink_target(
    candidate: Path,
    target_text: str,
    relative_name: str,
) -> tuple[Path, Path]:
    target_path = (
        Path(target_text) if target_text.startswith("/") else candidate.parent / target_text
    )
    try:
        first_hop_parent = target_path.parent.resolve(strict=True)
        final_target = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        _fail(f"active release contains a broken symlink: {relative_name}")
    return first_hop_parent, final_target


def _at_or_below(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _release_tree_inventory(
    release_path: Path, expected_symlinks: Mapping[str, str]
) -> tuple[set[str], dict[str, str]]:
    regular_files: set[str] = set()
    symlinks: dict[str, str] = {}
    total_regular_bytes = 0
    allowed_external_symlinks = {
        ".venv/bin/python",
        ".venv/bin/python3",
        ".venv/bin/python3.13",
    }
    allowed_target_texts = {"/usr/bin/python3.13", "/usr/local/bin/python3.13"}
    allowed_targets = {Path(value) for value in allowed_target_texts}

    def inventory_error(error: OSError) -> None:
        _fail(
            "active release tree cannot be inventoried completely: "
            f"{error.__class__.__name__}"
        )

    for directory, directory_names, file_names in os.walk(
        release_path, followlinks=False, onerror=inventory_error
    ):
        directory_path = Path(directory)
        for name in list(directory_names):
            candidate = directory_path / name
            metadata = candidate.lstat()
            relative_name = candidate.relative_to(release_path).as_posix()
            if stat.S_ISLNK(metadata.st_mode):
                directory_names.remove(name)
                symlinks[relative_name] = ""
            elif not stat.S_ISDIR(metadata.st_mode):
                _fail(f"active release contains a special path: {relative_name}")
        for name in file_names:
            candidate = directory_path / name
            metadata = candidate.lstat()
            relative_name = candidate.relative_to(release_path).as_posix()
            if stat.S_ISREG(metadata.st_mode):
                if relative_name != "SHA256SUMS":
                    regular_files.add(relative_name)
                    total_regular_bytes += metadata.st_size
            elif stat.S_ISLNK(metadata.st_mode):
                symlinks[relative_name] = ""
            else:
                _fail(f"active release contains a special path: {relative_name}")
    if total_regular_bytes > MAX_RELEASE_TREE_BYTES:
        _fail("active release regular-file inventory exceeds the size budget")
    if set(symlinks) != set(expected_symlinks):
        _fail("active release SYMLINKS.sha256 does not cover exactly every symlink")
    for relative_name, expected_target_hash in expected_symlinks.items():
        candidate = release_path.joinpath(*PurePosixPath(relative_name).parts)
        raw_target, first_metadata = _read_stable_symlink(
            candidate, release_path, f"release symlink {relative_name}"
        )
        try:
            target_text = raw_target.decode("ascii")
        except UnicodeError:
            _fail(f"release symlink target is not ASCII: {relative_name}")
        if not target_text or not SYMLINK_TARGET_RE.fullmatch(target_text):
            _fail(f"release symlink target has unsafe bytes: {relative_name}")
        if hashlib.sha256(raw_target).hexdigest() != expected_target_hash:
            _fail(f"release symlink target hash mismatch: {relative_name}")
        raw_is_absolute = target_text.startswith("/")
        first_hop_parent, resolved_target = _resolved_symlink_target(
            candidate, target_text, relative_name
        )
        if _at_or_below(resolved_target, release_path):
            if resolved_target == release_path:
                _fail(f"active release symlink resolves to release root: {relative_name}")
            if raw_is_absolute:
                _fail(
                    f"active release internal symlink target must be relative: {relative_name}"
                )
            if not _at_or_below(first_hop_parent, release_path):
                _fail(
                    "active release internal symlink first-hop parent escapes its tree: "
                    f"{relative_name}"
                )
        else:
            if (
                relative_name not in allowed_external_symlinks
                or resolved_target not in allowed_targets
            ):
                _fail(f"active release symlink escapes its tree: {relative_name}")
            if raw_is_absolute:
                if target_text not in allowed_target_texts:
                    _fail(
                        "active release external symlink has a non-canonical absolute "
                        f"target: {relative_name}"
                    )
            elif not _at_or_below(first_hop_parent, release_path):
                _fail(
                    "active release external symlink first-hop parent escapes its tree: "
                    f"{relative_name}"
                )
        second_raw_target, second_metadata = _read_stable_symlink(
            candidate, release_path, f"release symlink {relative_name}"
        )
        if (
            second_raw_target != raw_target
            or not FileSnapshot.from_read(b"", "", first_metadata).same_file(
                second_metadata
            )
        ):
            _fail(f"release symlink changed during validation: {relative_name}")
        second_first_hop_parent, second_resolved_target = _resolved_symlink_target(
            candidate, target_text, relative_name
        )
        if (
            second_first_hop_parent != first_hop_parent
            or second_resolved_target != resolved_target
        ):
            _fail(f"release symlink changed during validation: {relative_name}")
        symlinks[relative_name] = target_text
    return regular_files, symlinks


def _parse_release_manifest(release_path: Path) -> tuple[str, dict[str, str]]:
    manifest = release_path / "SHA256SUMS"
    manifest_snapshot = _read_stable_file(
        manifest,
        "active release SHA256SUMS",
        maximum_bytes=16 * 1024 * 1024,
        confinement_root=release_path,
    )
    entries: dict[str, str] = {}
    try:
        lines = manifest_snapshot.data.decode("ascii").splitlines()
    except UnicodeError:
        _fail("active release SHA256SUMS is not ASCII")
    if not lines:
        _fail("active release SHA256SUMS is empty")
    for line in lines:
        match = re.fullmatch(
            r"([0-9a-f]{64}) ([ *])([A-Za-z0-9._+@%/-]+)", line
        )
        if not match:
            _fail("active release SHA256SUMS contains a malformed record")
        expected_hash, relative_name = match.group(1), match.group(3)
        pure_path = PurePosixPath(relative_name)
        if (
            pure_path.is_absolute()
            or relative_name in entries
            or "\\" in relative_name
            or any(part in {"", ".", ".."} for part in pure_path.parts)
        ):
            _fail("active release SHA256SUMS contains an unsafe or duplicate path")
        entries[relative_name] = expected_hash
    if "SYMLINKS.sha256" not in entries:
        _fail("active release SHA256SUMS must cover SYMLINKS.sha256")
    expected_symlinks = _parse_symlink_manifest(release_path)
    regular_files, _symlinks = _release_tree_inventory(
        release_path, expected_symlinks
    )
    if set(entries) != regular_files:
        _fail("active release SHA256SUMS does not cover exactly every regular file")
    for relative_name, expected_hash in entries.items():
        pure_path = PurePosixPath(relative_name)
        candidate = release_path.joinpath(*pure_path.parts)
        try:
            candidate.resolve(strict=True).relative_to(release_path)
        except (OSError, ValueError):
            _fail(f"manifest entry escapes the active release: {relative_name}")
        if candidate.resolve(strict=True) != candidate:
            _fail(f"manifest entry traverses a symlink: {relative_name}")
        candidate_snapshot = _read_stable_file(
            candidate,
            f"manifest entry {relative_name}",
            maximum_bytes=MAX_RELEASE_FILE_BYTES,
            minimum_bytes=0,
            confinement_root=release_path,
            capture_data=False,
        )
        if candidate_snapshot.digest != expected_hash:
            _fail(f"active release manifest mismatch: {relative_name}")
    migration_root = release_path / "backend/src/main/resources/db/migration"
    expected_migration_names = {filename for _v, filename, _s, _c in EXPECTED_MIGRATIONS}
    try:
        migration_entries = list(os.scandir(migration_root))
    except OSError as error:
        _fail(f"active migration directory is unavailable: {error.__class__.__name__}")
    if {entry.name for entry in migration_entries} != expected_migration_names or any(
        not entry.is_file(follow_symlinks=False) for entry in migration_entries
    ):
        _fail("active migration directory must contain exactly regular V1-V8 files")
    _recheck_snapshot_path(manifest, manifest_snapshot, "active release SHA256SUMS")
    return manifest_snapshot.digest, entries


def _expected_database_migrations() -> list[dict[str, Any]]:
    return [
        {
            "checksum": checksum,
            "script": filename,
            "success": True,
            "version": version,
        }
        for version, filename, _sha256sum, checksum in EXPECTED_MIGRATIONS
    ]


def _expected_file_hashes() -> dict[str, str]:
    return {filename: sha256sum for _v, filename, sha256sum, _c in EXPECTED_MIGRATIONS}


def _release_binding(
    active_release_link: Path,
    install_root: Path,
    deploy_report_path: Path,
    approval_ticket: str,
) -> dict[str, str]:
    install_root = _real_directory(install_root, "release install root")
    if not active_release_link.is_absolute():
        _fail("active release link must be absolute")
    active_parent = _real_directory(
        active_release_link.parent, "active release link parent"
    )
    try:
        link_target_bytes, link_metadata = _read_stable_symlink(
            active_release_link, active_parent, "active release link"
        )
        link_target = os.fsdecode(link_target_bytes)
        release_path = active_release_link.resolve(strict=True)
    except OSError as error:
        _fail(f"active release link is unavailable: {error.__class__.__name__}")
    if link_target != str(release_path):
        _fail("active release link raw target must equal its canonical release path")
    if not release_path.is_dir():
        _fail("active release link must be a non-dangling symlink to a directory")
    if release_path.parent != install_root:
        _fail("active release must be one direct immutable child of the install root")
    release_id = release_path.name
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", release_id):
        _fail("derived active release id is unsafe")

    manifest_sha256, manifest_entries = _parse_release_manifest(release_path)
    for _version, filename, expected_hash, _checksum in EXPECTED_MIGRATIONS:
        relative_name = f"backend/src/main/resources/db/migration/{filename}"
        if manifest_entries.get(relative_name) != expected_hash:
            _fail(f"active release does not contain frozen migration {filename}")

    deploy, deploy_snapshot, _deploy_sidecar_snapshot = _load_checksummed_json(
        deploy_report_path, "deploy report", basename_only=False
    )
    if (
        stat.S_IMODE(deploy_snapshot.mode) != 0o600
        or deploy_snapshot.links != 1
        or stat.S_IMODE(_deploy_sidecar_snapshot.mode) != 0o600
        or _deploy_sidecar_snapshot.links != 1
    ):
        _fail("deploy report and sidecar must be private 0600 non-hardlink files")
    if deploy.get("status") != "pass":
        _fail("deploy report is not pass")
    if deploy.get("releaseId") != release_id:
        _fail("deploy report release id does not match the active release")
    if deploy.get("releasePath") != str(release_path):
        _fail("deploy report path does not match the active release")
    if deploy.get("releaseManifestSha256") != manifest_sha256:
        _fail("deploy report manifest does not match the active release")
    _identity(deploy.get("operator"), "deploy operator")
    deploy_ticket = _identity(deploy.get("changeTicket"), "deploy changeTicket")
    if deploy_ticket == approval_ticket:
        _fail("collector approval must be independent of the deploy change ticket")
    deploy_finished_at = _timestamp(deploy.get("finishedAt"), "deploy finishedAt")
    _true(deploy.get("projectionPublisherActive"), "deploy projectionPublisherActive")
    _false(deploy.get("publicRoutingChanged"), "deploy publicRoutingChanged")
    _false(deploy.get("legacyUnitsChanged"), "deploy legacyUnitsChanged")
    flyway = deploy.get("flyway")
    if not isinstance(flyway, dict):
        _fail("deploy flyway evidence must be an object")
    if flyway.get("schemaVersion") != "8":
        _fail("deploy Flyway schema is not the exact V1-V8 set")
    if _integer(flyway.get("migrationCount"), "deploy flyway.migrationCount", 8) != 8:
        _fail("deploy Flyway schema is not the exact V1-V8 set")
    _true(flyway.get("validated"), "deploy flyway.validated")
    for version, _filename, expected_hash, _checksum in EXPECTED_MIGRATIONS:
        if flyway.get(f"v{version}Sha256") != expected_hash:
            _fail(f"deploy Flyway V{version} checksum is invalid")
    try:
        final_link_target_bytes, final_link_metadata = _read_stable_symlink(
            active_release_link, active_parent, "active release link"
        )
        final_link_target = os.fsdecode(final_link_target_bytes)
        final_release_path = active_release_link.resolve(strict=True)
    except OSError as error:
        _fail(f"active release changed during validation: {error.__class__.__name__}")
    if (
        not FileSnapshot.from_read(b"", "", link_metadata).same_file(
            final_link_metadata
        )
        or final_link_target != link_target
        or final_release_path != release_path
    ):
        _fail("active release or manifest changed during validation")
    return {
        "deployFinishedAt": _format_timestamp(deploy_finished_at),
        "deployReportSha256": deploy_snapshot.digest,
        "deployTicket": deploy_ticket,
        "id": release_id,
        "sha256SumsSha256": manifest_sha256,
    }


def _validate_raw_evidence(
    value: Any,
    label: str,
    evidence_root: Path,
    now: datetime,
    max_age_seconds: int,
    capture_started_at: datetime,
    capture_finished_at: datetime,
) -> tuple[dict[str, Any], tuple[int, int]]:
    evidence = _object(value, label, {"bytes", "path", "sha256"})
    path_text = _string(evidence["path"], f"{label}.path")
    path = _within(Path(path_text), evidence_root, f"{label}.path")
    snapshot = _read_stable_file(
        path,
        label,
        maximum_bytes=MAX_RAW_EVIDENCE_BYTES,
        confinement_root=evidence_root,
    )
    if snapshot.links != 1:
        _fail(f"{label} must not be a hardlink")
    if snapshot.mode & 0o222:
        _fail(f"{label} must be immutable by file mode (no write bits)")
    expected_bytes = _integer(evidence["bytes"], f"{label}.bytes", 1)
    if expected_bytes > MAX_RAW_EVIDENCE_BYTES or snapshot.size != expected_bytes:
        _fail(f"{label} byte count does not match or exceeds the limit")
    expected_hash = _sha256(evidence["sha256"], f"{label}.sha256")
    if snapshot.digest != expected_hash:
        _fail(f"{label} SHA-256 does not match")
    modified = datetime.fromtimestamp(snapshot.mtime_ns / 1_000_000_000, tz=timezone.utc)
    _age_is_valid(modified, now, max_age_seconds, f"{label} mtime")
    if not (
        capture_started_at - timedelta(seconds=CLOCK_SKEW_SECONDS)
        <= modified
        <= capture_finished_at + timedelta(seconds=CLOCK_SKEW_SECONDS)
    ):
        _fail(f"{label} mtime must lie within its claimed capture window")
    return dict(evidence), (snapshot.device, snapshot.inode)


def _validate_migration_rows(value: Any, label: str) -> list[dict[str, Any]]:
    rows = _array(value, label)
    expected = _expected_database_migrations()
    if len(rows) != len(expected):
        _fail(f"{label} must be exactly the successful frozen V1-V8 rows")
    normalized: list[dict[str, Any]] = []
    for index, (row_value, expected_row) in enumerate(zip(rows, expected)):
        row = _object(
            row_value,
            f"{label}[{index}]",
            {"checksum", "script", "success", "version"},
        )
        version = _string(row["version"], f"{label}[{index}].version")
        script = _string(row["script"], f"{label}[{index}].script")
        checksum = _integer(row["checksum"], f"{label}[{index}].checksum", None)
        _true(row["success"], f"{label}[{index}].success")
        normalized_row = {
            "checksum": checksum,
            "script": script,
            "success": True,
            "version": version,
        }
        if normalized_row != expected_row:
            _fail(f"{label} must be exactly the successful frozen V1-V8 rows")
        normalized.append(normalized_row)
    return normalized


def _validate_policy(value: Any, label: str) -> dict[str, int]:
    policy = _object(value, label, EXPECTED_POLICY)
    for name, expected in EXPECTED_POLICY.items():
        if _integer(policy[name], f"{label}.{name}", 1) != expected:
            _fail(f"{label} must equal the approved collector policy")
    return dict(EXPECTED_POLICY)


def _validate_attestation(value: Any, label: str) -> dict[str, Any]:
    keys = {
        "controlledProviderResources",
        "evidenceOrigin",
        "fixtureBacked",
        "isolatedTargetCredentials",
        "legacyCollectorConcurrent",
        "legacyUnitsChanged",
        "liveProviderInteractions",
        "productionTrafficMutated",
        "routesChanged",
        "unitTestBacked",
    }
    evidence = _object(value, label, keys)
    if evidence["evidenceOrigin"] != "live-provider-shadow":
        _fail(f"{label}.evidenceOrigin must be live-provider-shadow")
    for name in (
        "controlledProviderResources",
        "isolatedTargetCredentials",
        "legacyCollectorConcurrent",
        "liveProviderInteractions",
    ):
        _true(evidence[name], f"{label}.{name}")
    for name in (
        "fixtureBacked",
        "legacyUnitsChanged",
        "productionTrafficMutated",
        "routesChanged",
        "unitTestBacked",
    ):
        _false(evidence[name], f"{label}.{name}")
    return dict(evidence)


def _validate_failures(value: Any, label: str) -> dict[str, Any]:
    names = {"ambiguousDiscovery", "authentication", "rateLimit", "transport"}
    failures = _object(value, label, names)
    result: dict[str, Any] = {}
    for name in sorted(names):
        item = _object(
            failures[name], f"{label}.{name}", {"attemptCount", "missingCounterIncrements"}
        )
        _integer(item["attemptCount"], f"{label}.{name}.attemptCount", 1)
        _zero(item["missingCounterIncrements"], f"{label}.{name}.missingCounterIncrements")
        result[name] = dict(item)
    return result


def _validate_platform(
    value: Any,
    label: str,
    policy: Mapping[str, int],
    evidence_root: Path,
    now: datetime,
    max_age_seconds: int,
    overall_start: datetime,
    overall_finish: datetime,
) -> tuple[dict[str, Any], tuple[int, int]]:
    keys = {
        "accountIds",
        "authoritativeMissingReason",
        "deletionLifecycle",
        "discovery",
        "finishedAt",
        "latestRevision",
        "platform",
        "providerMode",
        "rawEvidence",
        "replay",
        "runIds",
        "startedAt",
        "transientFailures",
    }
    record = _object(value, label, keys)
    platform = _string(record["platform"], f"{label}.platform")
    if platform not in PLATFORMS:
        _fail(f"{label}.platform is unsupported")
    provider_mode = _string(record["providerMode"], f"{label}.providerMode")
    if provider_mode not in PROVIDER_MODES[platform]:
        _fail(f"{label}.providerMode is not valid for {platform}")
    reason = _string(
        record["authoritativeMissingReason"], f"{label}.authoritativeMissingReason"
    )
    if reason not in AUTHORITATIVE_MISSING_REASONS[platform]:
        _fail(f"{label}.authoritativeMissingReason is not provider-authoritative")

    started_at = _timestamp(record["startedAt"], f"{label}.startedAt")
    finished_at = _timestamp(record["finishedAt"], f"{label}.finishedAt")
    if not overall_start <= started_at < finished_at <= overall_finish:
        _fail(f"{label} timestamps must be inside the overall shadow window")
    _age_is_valid(finished_at, now, max_age_seconds, f"{label}.finishedAt")

    account_ids = _array(record["accountIds"], f"{label}.accountIds")
    if not account_ids:
        _fail(f"{label}.accountIds must not be empty")
    validated_accounts = [
        _uuid(item, f"{label}.accountIds[{index}]")
        for index, item in enumerate(account_ids)
    ]
    if len(set(validated_accounts)) != len(validated_accounts):
        _fail(f"{label}.accountIds must be unique")

    run_ids = _array(record["runIds"], f"{label}.runIds")
    if len(run_ids) < 4:
        _fail(f"{label}.runIds must contain at least four distinct shadow runs")
    validated_runs = [
        _uuid(item, f"{label}.runIds[{index}]") for index, item in enumerate(run_ids)
    ]
    if len(set(validated_runs)) != len(validated_runs):
        _fail(f"{label}.runIds must be unique")
    run_set = set(validated_runs)

    discovery = _object(
        record["discovery"],
        f"{label}.discovery",
        {
            "cursorWrapCount",
            "cycleCount",
            "discoveryPagePublicationCount",
            "exactLookupRefreshCount",
            "trackedPublicationCount",
        },
    )
    _integer(discovery["cursorWrapCount"], f"{label}.discovery.cursorWrapCount", 1)
    _integer(discovery["cycleCount"], f"{label}.discovery.cycleCount", 2)
    page_count = _integer(
        discovery["discoveryPagePublicationCount"],
        f"{label}.discovery.discoveryPagePublicationCount",
        1,
    )
    tracked_count = _integer(
        discovery["trackedPublicationCount"],
        f"{label}.discovery.trackedPublicationCount",
        2,
    )
    if tracked_count <= page_count:
        _fail(f"{label}.discovery must cover historical publications beyond discovery")
    _integer(
        discovery["exactLookupRefreshCount"],
        f"{label}.discovery.exactLookupRefreshCount",
        1,
    )

    lifecycle = _object(
        record["deletionLifecycle"],
        f"{label}.deletionLifecycle",
        {
            "confirmedAfterChecks",
            "confirmedRunId",
            "controlledPublication",
            "deletedAtCleared",
            "firstMissingRunId",
            "historicalRowCountAfterRediscovery",
            "historicalRowCountBefore",
            "identityRowsPreserved",
            "publicationRowPreserved",
            "rediscoveredRunId",
            "secondMissingRunId",
            "stateAfterRediscovery",
        },
    )
    _true(lifecycle["controlledPublication"], f"{label}.deletionLifecycle.controlledPublication")
    _true(lifecycle["deletedAtCleared"], f"{label}.deletionLifecycle.deletedAtCleared")
    _true(lifecycle["identityRowsPreserved"], f"{label}.deletionLifecycle.identityRowsPreserved")
    _true(lifecycle["publicationRowPreserved"], f"{label}.deletionLifecycle.publicationRowPreserved")
    if lifecycle["stateAfterRediscovery"] != "present":
        _fail(f"{label}.deletionLifecycle.stateAfterRediscovery must be present")
    confirmed_after_checks = _integer(
        lifecycle["confirmedAfterChecks"],
        f"{label}.deletionLifecycle.confirmedAfterChecks",
        2,
    )
    if confirmed_after_checks != policy["deletionConfirmationChecks"]:
        _fail(f"{label}.deletionLifecycle does not match the deletion threshold")
    first_run = _uuid(lifecycle["firstMissingRunId"], f"{label}.deletionLifecycle.firstMissingRunId")
    second_run = _uuid(lifecycle["secondMissingRunId"], f"{label}.deletionLifecycle.secondMissingRunId")
    confirmed_run = _uuid(lifecycle["confirmedRunId"], f"{label}.deletionLifecycle.confirmedRunId")
    rediscovered_run = _uuid(lifecycle["rediscoveredRunId"], f"{label}.deletionLifecycle.rediscoveredRunId")
    if confirmed_run != second_run or len({first_run, second_run, rediscovered_run}) != 3:
        _fail(f"{label}.deletionLifecycle must use distinct first/second/rediscovery runs")
    if not {first_run, second_run, rediscovered_run}.issubset(run_set):
        _fail(f"{label}.deletionLifecycle references an unknown run")
    before = _integer(
        lifecycle["historicalRowCountBefore"],
        f"{label}.deletionLifecycle.historicalRowCountBefore",
        1,
    )
    after = _integer(
        lifecycle["historicalRowCountAfterRediscovery"],
        f"{label}.deletionLifecycle.historicalRowCountAfterRediscovery",
        before,
    )
    if after < before:
        _fail(f"{label}.deletionLifecycle lost historical rows")

    replay = _object(
        record["replay"],
        f"{label}.replay",
        {
            "attemptCount",
            "newDatasetRevisionCount",
            "newDeletionObservationCount",
            "newOutboxEventCount",
            "newSnapshotCount",
            "runId",
        },
    )
    _integer(replay["attemptCount"], f"{label}.replay.attemptCount", 2)
    replay_run = _uuid(replay["runId"], f"{label}.replay.runId")
    if replay_run not in run_set:
        _fail(f"{label}.replay.runId references an unknown run")
    for name in (
        "newDatasetRevisionCount",
        "newDeletionObservationCount",
        "newOutboxEventCount",
        "newSnapshotCount",
    ):
        _zero(replay[name], f"{label}.replay.{name}")

    failures = _validate_failures(record["transientFailures"], f"{label}.transientFailures")
    latest_revision = _integer(record["latestRevision"], f"{label}.latestRevision", 1)
    raw_evidence, raw_identity = _validate_raw_evidence(
        record["rawEvidence"],
        f"{label}.rawEvidence",
        evidence_root,
        now,
        max_age_seconds,
        started_at,
        finished_at,
    )
    normalized = dict(record)
    normalized["accountIds"] = validated_accounts
    normalized["runIds"] = validated_runs
    normalized["discovery"] = dict(discovery)
    normalized["deletionLifecycle"] = dict(lifecycle)
    normalized["replay"] = dict(replay)
    normalized["transientFailures"] = failures
    normalized["latestRevision"] = latest_revision
    normalized["rawEvidence"] = raw_evidence
    return normalized, raw_identity


def _validate_duplicates(value: Any, label: str) -> dict[str, int]:
    names = {
        "accountExternalIdentity",
        "accountIdentityHistory",
        "datasetRevision",
        "deletionObservation",
        "outboxEvent",
        "publication",
        "publicationMetricSnapshot",
    }
    duplicates = _object(value, label, names)
    for name in names:
        _zero(duplicates[name], f"{label}.{name}")
    return dict(duplicates)


def _validate_projection(
    value: Any, label: str, platforms: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    projection = _object(
        value,
        label,
        {"latestCollectorRevision", "latestDatasetRevision", "states"},
    )
    collector_revision = _integer(
        projection["latestCollectorRevision"], f"{label}.latestCollectorRevision", 1
    )
    dataset_revision = _integer(
        projection["latestDatasetRevision"], f"{label}.latestDatasetRevision", 1
    )
    if collector_revision != dataset_revision:
        _fail(f"{label} is not published at the latest collector revision")
    if max(item["latestRevision"] for item in platforms) != collector_revision:
        _fail(f"{label}.latestCollectorRevision is not the newest platform revision")
    states = _object(projection["states"], f"{label}.states", PROJECTIONS)
    normalized_states: dict[str, dict[str, Any]] = {}
    for name in PROJECTIONS:
        state = _object(
            states[name], f"{label}.states.{name}", {"revision", "status"}
        )
        state_revision = _integer(
            state["revision"], f"{label}.states.{name}.revision", 1
        )
        if state["status"] != "ready" or state_revision != dataset_revision:
            _fail(f"{label}.states.{name} is stale")
        normalized_states[name] = {"revision": state_revision, "status": "ready"}
    return {
        "latestCollectorRevision": collector_revision,
        "latestDatasetRevision": dataset_revision,
        "states": normalized_states,
    }


def _validate_database(
    value: Any,
    label: str,
    evidence_root: Path,
    now: datetime,
    max_age_seconds: int,
    capture_started_at: datetime,
    capture_finished_at: datetime,
) -> tuple[dict[str, Any], tuple[int, int]]:
    database = _object(value, label, {"name", "rawEvidence"})
    name = _string(database["name"], f"{label}.name")
    if not SAFE_DATABASE_RE.fullmatch(name) or NON_ACCEPTANCE_DATABASE_RE.search(name):
        _fail(f"{label}.name is not a production-like shadow database identifier")
    raw_evidence, raw_identity = _validate_raw_evidence(
        database["rawEvidence"],
        f"{label}.rawEvidence",
        evidence_root,
        now,
        max_age_seconds,
        capture_started_at,
        capture_finished_at,
    )
    return {"name": name, "rawEvidence": raw_evidence}, raw_identity


def _validate_report_body(
    value: Mapping[str, Any],
    *,
    evidence_root: Path,
    now: datetime,
    max_age_seconds: int,
    operator: str,
    approval_ticket: str,
    source_namespace: str,
    release_binding: Mapping[str, str] | None,
    is_source: bool,
) -> dict[str, Any]:
    common_keys = {
        "approvalTicket",
        "attestation",
        "database",
        "duplicates",
        "environment",
        "finishedAt",
        "operator",
        "platforms",
        "policy",
        "projection",
        "sourceNamespace",
        "startedAt",
        "status",
    }
    if is_source:
        required_keys = common_keys | {
            "evidenceType",
            "evidenceVersion",
            "flywayDatabaseMigrations",
        }
    else:
        required_keys = common_keys | {
            "flyway",
            "generatedAt",
            "release",
            "reportType",
            "reportVersion",
        }
    body = _object(value, "source evidence" if is_source else "collector report", required_keys)
    if body["status"] != "pass" or body["environment"] != "production-like":
        _fail("collector evidence must be a production-like pass")
    if body["operator"] != operator:
        _fail("collector evidence operator does not match the expected operator")
    if body["approvalTicket"] != approval_ticket:
        _fail("collector evidence does not match the dedicated approval")
    if body["sourceNamespace"] != source_namespace:
        _fail("collector evidence does not match the source namespace")

    started_at = _timestamp(body["startedAt"], "collector evidence startedAt")
    finished_at = _timestamp(body["finishedAt"], "collector evidence finishedAt")
    if started_at >= finished_at:
        _fail("collector evidence time window is empty or reversed")
    _age_is_valid(finished_at, now, max_age_seconds, "collector evidence finishedAt")
    if release_binding is None:
        _fail("collector evidence is missing derived deploy provenance")
    deploy_finished_at = _timestamp(
        release_binding.get("deployFinishedAt"), "release.deployFinishedAt"
    )
    if deploy_finished_at >= started_at:
        _fail("shadow rehearsal must start after the bound release deployment")
    attestation = _validate_attestation(body["attestation"], "attestation")
    policy = _validate_policy(body["policy"], "policy")
    database, database_raw_identity = _validate_database(
        body["database"],
        "database",
        evidence_root,
        now,
        max_age_seconds,
        started_at,
        finished_at,
    )

    platforms_value = _array(body["platforms"], "platforms")
    if len(platforms_value) != 4:
        _fail("platforms must contain exactly four records")
    platforms: list[dict[str, Any]] = []
    raw_identities = {database_raw_identity}
    for index, item in enumerate(platforms_value):
        platform, raw_identity = _validate_platform(
            item,
            f"platforms[{index}]",
            policy,
            evidence_root,
            now,
            max_age_seconds,
            started_at,
            finished_at,
        )
        if raw_identity in raw_identities:
            _fail("every database/platform record must use a distinct raw evidence inode")
        raw_identities.add(raw_identity)
        platforms.append(platform)
    if sorted(item["platform"] for item in platforms) != list(PLATFORMS):
        _fail("platforms must contain Telegram, VK, MAX and RUTUBE exactly once")

    projection = _validate_projection(body["projection"], "projection", platforms)
    duplicates = _validate_duplicates(body["duplicates"], "duplicates")
    normalized: dict[str, Any] = {
        "approvalTicket": approval_ticket,
        "attestation": attestation,
        "database": database,
        "duplicates": duplicates,
        "environment": "production-like",
        "finishedAt": body["finishedAt"],
        "operator": operator,
        "platforms": platforms,
        "policy": policy,
        "projection": projection,
        "sourceNamespace": source_namespace,
        "startedAt": body["startedAt"],
        "status": "pass",
    }

    if is_source:
        evidence_version = _integer(
            body["evidenceVersion"], "source evidenceVersion", 1
        )
        if body["evidenceType"] != SOURCE_TYPE or evidence_version != SOURCE_VERSION:
            _fail("source evidence type/version is unsupported")
        migrations = _validate_migration_rows(
            body["flywayDatabaseMigrations"], "flywayDatabaseMigrations"
        )
        normalized["flywayDatabaseMigrations"] = migrations
        return normalized

    report_version = _integer(body["reportVersion"], "collector reportVersion", 1)
    if body["reportType"] != REPORT_TYPE or report_version != REPORT_VERSION:
        _fail("collector report type/version is unsupported")
    generated_at = _timestamp(body["generatedAt"], "collector report generatedAt")
    _age_is_valid(generated_at, now, max_age_seconds, "collector report generatedAt")
    if generated_at < finished_at:
        _fail("collector report was generated before the shadow run finished")
    release = _object(
        body["release"],
        "release",
        {
            "deployFinishedAt",
            "deployReportSha256",
            "deployTicket",
            "id",
            "sha256SumsSha256",
        },
    )
    _timestamp(release["deployFinishedAt"], "release.deployFinishedAt")
    _sha256(release["deployReportSha256"], "release.deployReportSha256")
    _identity(release["deployTicket"], "release.deployTicket")
    _identity(release["id"], "release.id")
    _sha256(release["sha256SumsSha256"], "release.sha256SumsSha256")
    if dict(release) != dict(release_binding):
        _fail("collector report is not bound to the derived active release")
    flyway = _object(
        body["flyway"],
        "flyway",
        {"databaseMigrations", "fileSha256", "migrationCount", "schemaVersion"},
    )
    schema_version = _integer(flyway["schemaVersion"], "flyway.schemaVersion", 1)
    migration_count = _integer(flyway["migrationCount"], "flyway.migrationCount", 1)
    if schema_version != 8 or migration_count != 8:
        _fail("collector report Flyway version/count must be exactly V1-V8")
    if flyway["fileSha256"] != _expected_file_hashes():
        _fail("collector report Flyway file hashes do not match frozen V1-V8")
    migrations = _validate_migration_rows(flyway["databaseMigrations"], "flyway.databaseMigrations")
    normalized.update(
        {
            "flyway": {
                "databaseMigrations": migrations,
                "fileSha256": _expected_file_hashes(),
                "migrationCount": 8,
                "schemaVersion": 8,
            },
            "generatedAt": body["generatedAt"],
            "release": dict(release),
            "reportType": REPORT_TYPE,
            "reportVersion": REPORT_VERSION,
        }
    )
    return normalized


def _validate_context_values(
    operator: str, approval_ticket: str, source_namespace: str, max_age_seconds: int
) -> tuple[str, str, str]:
    if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 7 * 86_400:
        _fail("max age must be between 1 and 604800 seconds")
    return (
        _identity(operator, "operator"),
        _identity(approval_ticket, "approval ticket"),
        _source_namespace(source_namespace, "source namespace"),
    )


def _check_private_snapshot(
    snapshot: FileSnapshot,
    label: str,
    now: datetime,
    max_age_seconds: int,
) -> None:
    if stat.S_IMODE(snapshot.mode) != 0o600:
        _fail(f"{label} must have mode 0600")
    if snapshot.links != 1:
        _fail(f"{label} must not be a hardlink")
    modified = datetime.fromtimestamp(snapshot.mtime_ns / 1_000_000_000, tz=timezone.utc)
    _age_is_valid(modified, now, max_age_seconds, f"{label} mtime")


def _write_new_private(path: Path, payload: bytes, confinement_root: Path) -> None:
    if not path.is_absolute():
        _fail("output report path must be absolute")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        _fail("this platform cannot safely create evidence with O_NOFOLLOW/O_DIRECTORY")
    parent_descriptor: int | None = None
    descriptor: int | None = None
    created = False
    try:
        parent_descriptor, basename = _open_parent_directory(
            path,
            "output report",
            confinement_root,
        )
        descriptor = os.open(
            basename,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | nofollow
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        created = True
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(parent_descriptor)
    except FileExistsError:
        _fail("output report already exists; evidence is never overwritten")
    except EvidenceError:
        raise
    except OSError as error:
        if created and parent_descriptor is not None:
            try:
                os.unlink(basename, dir_fd=parent_descriptor)
                os.fsync(parent_descriptor)
            except OSError:
                pass
        _fail(f"cannot write evidence: {error.__class__.__name__}")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def _new_path_below(path: Path, root: Path, label: str) -> None:
    if not path.is_absolute():
        _fail(f"{label} must be absolute")
    try:
        resolved_parent = path.parent.resolve(strict=True)
        resolved_parent.relative_to(root)
    except (OSError, ValueError):
        _fail(f"{label} parent must resolve below the evidence root")
    if resolved_parent != path.parent:
        _fail(f"{label} parent must not traverse a symlink or alias")


def seal_report(
    source: Mapping[str, Any],
    *,
    output_path: Path,
    evidence_root: Path,
    active_release_link: Path,
    install_root: Path,
    deploy_report_path: Path,
    operator: str,
    approval_ticket: str,
    source_namespace: str,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    operator, approval_ticket, source_namespace = _validate_context_values(
        operator, approval_ticket, source_namespace, max_age_seconds
    )
    evidence_root = _real_directory(evidence_root, "evidence root")
    release = _release_binding(
        active_release_link,
        install_root,
        deploy_report_path,
        approval_ticket,
    )
    validated = _validate_report_body(
        source,
        evidence_root=evidence_root,
        now=now,
        max_age_seconds=max_age_seconds,
        operator=operator,
        approval_ticket=approval_ticket,
        source_namespace=source_namespace,
        release_binding=release,
        is_source=True,
    )
    migrations = validated.pop("flywayDatabaseMigrations")
    report = {
        **validated,
        "flyway": {
            "databaseMigrations": migrations,
            "fileSha256": _expected_file_hashes(),
            "migrationCount": 8,
            "schemaVersion": 8,
        },
        "generatedAt": _format_timestamp(now),
        "release": release,
        "reportType": REPORT_TYPE,
        "reportVersion": REPORT_VERSION,
    }
    # Validate the produced representation before any durable write.
    report = _validate_report_body(
        report,
        evidence_root=evidence_root,
        now=now,
        max_age_seconds=max_age_seconds,
        operator=operator,
        approval_ticket=approval_ticket,
        source_namespace=source_namespace,
        release_binding=release,
        is_source=False,
    )
    if _release_binding(
        active_release_link,
        install_root,
        deploy_report_path,
        approval_ticket,
    ) != release:
        _fail("active release provenance changed before evidence sealing")
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    sidecar_path = Path(f"{output_path}.sha256")
    _new_path_below(output_path, evidence_root, "output report")
    _new_path_below(sidecar_path, evidence_root, "output SHA-256 sidecar")
    if sidecar_path.exists() or sidecar_path.is_symlink():
        _fail("output SHA-256 sidecar already exists; evidence is never overwritten")
    _write_new_private(output_path, payload, evidence_root)
    digest = hashlib.sha256(payload).hexdigest()
    try:
        _write_new_private(
            sidecar_path,
            f"{digest}  {output_path.name}\n".encode("ascii"),
            evidence_root,
        )
    except Exception:
        # This report was created by this invocation and is incomplete without its sidecar.
        try:
            output_path.unlink()
        except OSError:
            pass
        raise
    return report


def verify_report(
    report_path: Path,
    *,
    evidence_root: Path,
    active_release_link: Path,
    install_root: Path,
    deploy_report_path: Path,
    operator: str,
    approval_ticket: str,
    source_namespace: str,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    operator, approval_ticket, source_namespace = _validate_context_values(
        operator, approval_ticket, source_namespace, max_age_seconds
    )
    evidence_root = _real_directory(evidence_root, "evidence root")
    release = _release_binding(
        active_release_link,
        install_root,
        deploy_report_path,
        approval_ticket,
    )
    report_path = _within(report_path, evidence_root, "collector report")
    sidecar_path = Path(f"{report_path}.sha256")
    _within(sidecar_path, evidence_root, "collector report SHA-256 sidecar")
    report, report_snapshot, sidecar_snapshot = _load_checksummed_json(
        report_path,
        "collector report",
        basename_only=True,
        confinement_root=evidence_root,
    )
    _check_private_snapshot(
        report_snapshot, "collector report", now, max_age_seconds
    )
    _check_private_snapshot(
        sidecar_snapshot,
        "collector report SHA-256 sidecar",
        now,
        max_age_seconds,
    )
    validated = _validate_report_body(
        report,
        evidence_root=evidence_root,
        now=now,
        max_age_seconds=max_age_seconds,
        operator=operator,
        approval_ticket=approval_ticket,
        source_namespace=source_namespace,
        release_binding=release,
        is_source=False,
    )
    if _release_binding(
        active_release_link,
        install_root,
        deploy_report_path,
        approval_ticket,
    ) != release:
        _fail("active release provenance changed during evidence verification")
    return validated


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Seal or verify collector parity evidence. This checks artifact "
            "integrity and declared invariants; it does not prove live facts, "
            "and external approval remains required."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("seal", "verify"):
        child = subparsers.add_parser(command)
        child.add_argument("--active-release-link", type=Path, required=True)
        child.add_argument("--install-root", type=Path, required=True)
        child.add_argument("--deploy-report", type=Path, required=True)
        child.add_argument("--evidence-root", type=Path, required=True)
        child.add_argument("--operator", required=True)
        child.add_argument("--approval-ticket", required=True)
        child.add_argument("--source-namespace", required=True)
        child.add_argument(
            "--max-age-seconds", type=int, default=DEFAULT_MAX_AGE_SECONDS
        )
    seal = subparsers.choices["seal"]
    seal.add_argument("--source", type=Path, required=True)
    seal.add_argument("--output", type=Path, required=True)
    verify = subparsers.choices["verify"]
    verify.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    common = {
        "evidence_root": arguments.evidence_root,
        "active_release_link": arguments.active_release_link,
        "install_root": arguments.install_root,
        "deploy_report_path": arguments.deploy_report,
        "operator": arguments.operator,
        "approval_ticket": arguments.approval_ticket,
        "source_namespace": arguments.source_namespace,
        "max_age_seconds": arguments.max_age_seconds,
    }
    try:
        if arguments.command == "seal":
            source = _load_json(arguments.source, "collector source evidence")
            report = seal_report(source, output_path=arguments.output, **common)
            report_path = arguments.output
        else:
            report = verify_report(arguments.report, **common)
            report_path = arguments.report
    except EvidenceError as error:
        print(
            json.dumps(
                {
                    "command": arguments.command,
                    "error": str(error),
                    "status": "fail",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 65
    print(
        json.dumps(
            {
                "command": arguments.command,
                "generatedAt": report["generatedAt"],
                "report": str(report_path),
                "releaseId": report["release"]["id"],
                "status": "pass",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
