from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlsplit

from .journal import ReverseSyncJournal
from .postgres import PostgresReverseSource
from .service import ReverseSyncService
from .sqlite_target import LegacySqliteTarget


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise ValueError("invalid reverse-sync command arguments")


def build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        prog="mranked-pg-to-legacy-sync",
        description="Bounded PostgreSQL-to-legacy rollback compatibility projection.",
    )
    parser.add_argument(
        "--postgres-dsn",
        default=None,
        help="password-free target PostgreSQL DSN; prefer REVERSE_SYNC_DATABASE_URL",
    )
    parser.add_argument(
        "--legacy-sqlite",
        type=Path,
        default=_environment_path("LEGACY_SQLITE_PATH"),
    )
    parser.add_argument(
        "--journal-path",
        type=Path,
        default=_environment_path("REVERSE_SYNC_JOURNAL_PATH"),
    )
    parser.add_argument(
        "--source-namespace",
        default=os.getenv("MIGRATION_SOURCE_NAMESPACE"),
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=_environment_path("REVERSE_SYNC_REPORT_PATH"),
    )
    parser.add_argument(
        "--min-free-bytes",
        type=int,
        default=int(os.getenv("REVERSE_SYNC_MIN_FREE_BYTES", str(64 * 1024 * 1024))),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight")
    start = commands.add_parser("start")
    start.add_argument("--rollback-window-hours", required=True, type=int)
    start.add_argument("--operator", required=True)
    start.add_argument("--ticket", required=True)
    commands.add_parser("once")
    run = commands.add_parser("run")
    run.add_argument(
        "--poll-seconds",
        type=float,
        default=float(os.getenv("REVERSE_SYNC_POLL_SECONDS", "5")),
    )
    drain = commands.add_parser("drain")
    drain.add_argument("--operator", required=True)
    drain.add_argument("--ticket", required=True)
    commands.add_parser("verify")
    commands.add_parser("stop")
    commands.add_parser("status")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments: argparse.Namespace | None = None
    report_path: Path | None = None
    try:
        arguments = build_parser().parse_args(argv)
        report_path = _validated_paths(arguments)
        if report_path is not None:
            _atomic_report(
                report_path,
                {"command": arguments.command, "status": "running"},
            )
        service = _service(arguments)
        if arguments.command == "preflight":
            result = service.preflight()
        elif arguments.command == "start":
            result = service.start(
                rollback_window_hours=arguments.rollback_window_hours,
                operator=arguments.operator,
                ticket=arguments.ticket,
            )
        elif arguments.command == "once":
            result = service.once()
        elif arguments.command == "run":
            result = service.run(poll_seconds=arguments.poll_seconds)
        elif arguments.command == "drain":
            result = service.drain(
                operator=arguments.operator,
                ticket=arguments.ticket,
            )
        elif arguments.command == "verify":
            result = service.verify()
        elif arguments.command == "stop":
            result = service.stop()
        elif arguments.command == "status":
            result = service.status()
        else:  # pragma: no cover - argparse owns the command choices
            raise AssertionError("unreachable reverse-sync command")
        payload = {"command": arguments.command, **result}
        if report_path is not None:
            _atomic_report(report_path, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
        return _result_exit_code(arguments.command, result)
    except KeyboardInterrupt:
        payload = {
            "command": getattr(arguments, "command", None),
            "status": "interrupted",
        }
        if report_path is not None:
            _best_effort_report(report_path, payload)
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        return 130
    except Exception as error:
        # Never emit exception text: driver errors can include DSNs or server
        # details. Operators correlate the type with restricted service logs.
        payload = {
            "command": getattr(arguments, "command", None),
            "status": "failed",
            "errorCode": type(error).__name__,
        }
        if report_path is not None:
            _best_effort_report(report_path, payload)
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        return 1


def _service(arguments: argparse.Namespace) -> ReverseSyncService:
    explicit_dsn = str(arguments.postgres_dsn or "").strip()
    if explicit_dsn and _dsn_contains_password(explicit_dsn):
        raise ValueError("password-bearing PostgreSQL DSN is forbidden in argv")
    dsn = explicit_dsn or str(
        os.getenv("REVERSE_SYNC_DATABASE_URL")
        or os.getenv("TARGET_DATABASE_URL")
        or ""
    ).strip()
    namespace = str(arguments.source_namespace or "").strip()
    if not dsn:
        raise ValueError("REVERSE_SYNC_DATABASE_URL is required")
    if arguments.legacy_sqlite is None:
        raise ValueError("LEGACY_SQLITE_PATH is required")
    if arguments.journal_path is None:
        raise ValueError("REVERSE_SYNC_JOURNAL_PATH is required")
    if not namespace:
        raise ValueError("MIGRATION_SOURCE_NAMESPACE is required")
    _validated_paths(arguments)
    return ReverseSyncService(
        PostgresReverseSource(dsn, namespace),
        LegacySqliteTarget(
            arguments.legacy_sqlite,
            namespace,
            min_free_bytes=arguments.min_free_bytes,
        ),
        ReverseSyncJournal(arguments.journal_path),
    )


def _validated_paths(arguments: argparse.Namespace) -> Path | None:
    """Reject every path that SQLite or the process lock may create or replace."""

    if arguments.legacy_sqlite is None or arguments.journal_path is None:
        return None
    legacy = Path(os.path.abspath(arguments.legacy_sqlite.expanduser()))
    journal = Path(os.path.abspath(arguments.journal_path.expanduser()))
    for candidate in (legacy, journal):
        if candidate.is_symlink() or _has_symlink_ancestor(candidate.parent):
            raise ValueError("reverse-sync database paths must not traverse symlinks")
    legacy_reserved = (
        *_sqlite_reserved_paths(legacy),
        legacy.with_name(f".{legacy.name}.reverse-sync.lock"),
    )
    journal_reserved = (
        *_sqlite_reserved_paths(journal),
        journal.with_name(f".{journal.name}.lock"),
    )
    if any(
        left == right or _same_existing_file(left, right)
        for left in legacy_reserved
        for right in journal_reserved
    ):
        raise ValueError(
            "legacy SQLite and reverse-sync journal reserved paths must be distinct"
        )
    if arguments.report_path is None:
        return None
    report = Path(os.path.abspath(arguments.report_path.expanduser()))
    if report.is_symlink() or _has_symlink_ancestor(report.parent):
        raise ValueError("reverse-sync report path must not traverse symlinks")
    protected_paths = (*legacy_reserved, *journal_reserved)
    if any(
        report == protected or _same_existing_file(report, protected)
        for protected in protected_paths
    ):
        raise ValueError(
            "reverse-sync report must not replace a database, sidecar, or lock"
        )
    return report


def _sqlite_reserved_paths(path: Path) -> tuple[Path, Path, Path, Path]:
    return (
        path,
        Path(f"{path}-wal"),
        Path(f"{path}-shm"),
        Path(f"{path}-journal"),
    )


def _environment_path(name: str) -> Path | None:
    value = os.getenv(name, "").strip()
    return Path(value) if value else None


def _same_existing_file(first: Path, second: Path) -> bool:
    try:
        return first.samefile(second)
    except FileNotFoundError:
        return False


def _has_symlink_ancestor(path: Path) -> bool:
    candidate = path
    while candidate != candidate.parent:
        if candidate.is_symlink():
            return True
        candidate = candidate.parent
    return candidate.is_symlink()


def _dsn_contains_password(dsn: str) -> bool:
    normalized = str(dsn).strip()
    if not normalized:
        return False
    if "password=" in normalized.casefold():
        return True
    if "://" not in normalized:
        return False
    try:
        parsed = urlsplit(normalized)
        if parsed.password is not None:
            return True
        return any(
            key.casefold() == "password"
            for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
        )
    except ValueError:
        return True


def _result_exit_code(command: str, result: Mapping[str, Any]) -> int:
    if command == "once" and result.get("caughtUp") is not True:
        return 75
    if command == "status":
        if int(result.get("lagRevisionCount", 0)) > 0:
            return 75
        if result.get("unchangedSinceDrain") is False:
            return 75
    return 0


def _best_effort_report(path: Path, payload: Mapping[str, Any]) -> None:
    try:
        _atomic_report(path, payload)
    except Exception:
        # The stderr result remains authoritative if the report filesystem is
        # unavailable. Never replace the original command error with a report
        # write error that may contain path or host details.
        return


def _atomic_report(path: Path, payload: Mapping[str, Any]) -> None:
    destination = Path(os.path.abspath(path.expanduser()))
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.is_symlink() or _has_symlink_ancestor(destination.parent):
        raise ValueError("reverse-sync report path must not be a symlink")
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".staging", dir=destination.parent,
    )
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2, default=str)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
