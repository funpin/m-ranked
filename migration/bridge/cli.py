from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Sequence

from .mapping import mapping_as_rows, validate_mapping
from .fixture import build_golden_fixture
from .model import BridgeOptions
from .report import inventory_payload, write_reports
from .service import BridgeService
from .source import LegacySource, create_online_backup
from .target import PostgresTarget


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        prog="python -m migration.bridge",
        description="Safe, idempotent M-Ranked SQLite to PostgreSQL bridge",
    )
    subcommands = command.add_subparsers(dest="command", required=True)

    backup = subcommands.add_parser("backup", help="Create verified SQLite online backup")
    backup.add_argument("source", type=Path)
    backup.add_argument("destination", type=Path)

    inspect = subcommands.add_parser(
        "inspect", help="Validate source and write machine/human-readable inventory"
    )
    inspect.add_argument("source", type=Path)
    inspect.add_argument("--report-dir", type=Path, default=Path("migration/reports"))
    inspect.add_argument("--stem", default=None)

    mapping = subcommands.add_parser("mapping", help="Emit the exhaustive column mapping matrix")
    mapping.add_argument("--format", choices=("json", "markdown"), default="markdown")

    fixture = subcommands.add_parser(
        "fixture", help="Build a deterministic edge-case SQLite golden fixture"
    )
    fixture.add_argument("destination", type=Path)
    fixture.add_argument("--revision", type=int, choices=(1, 2), default=1)

    import_data = subcommands.add_parser(
        "import",
        help="Run a resumable, idempotent import and write reconciliation reports",
    )
    import_data.add_argument("source", type=Path, help="Verified immutable SQLite backup")
    import_data.add_argument(
        "--source-namespace",
        required=True,
        help="Stable logical source name; changing it changes deterministic identities",
    )
    import_data.add_argument(
        "--snapshot-kind",
        choices=("s0", "catch_up", "s_final", "fixture"),
        required=True,
    )
    import_data.add_argument(
        "--postgres-dsn",
        help="PostgreSQL DSN. Required unless --dry-run is used; never written to reports",
    )
    import_data.add_argument("--batch-size", type=int, default=1_000)
    import_data.add_argument("--no-resume", action="store_true")
    import_data.add_argument("--dry-run", action="store_true")
    import_data.add_argument("--report-dir", type=Path, default=Path("migration/reports"))
    import_data.add_argument("--stem", default=None)

    return command


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "backup":
        print(json.dumps(create_online_backup(args.source, args.destination), indent=2))
        return 0
    if args.command == "fixture":
        print(
            json.dumps(
                build_golden_fixture(args.destination, revision=args.revision),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "mapping":
        rows = mapping_as_rows()
        if args.format == "json":
            print(json.dumps(rows, ensure_ascii=False, sort_keys=True, indent=2))
        else:
            print("| SQLite column | Status | Target | Rule |")
            print("|---|---|---|---|")
            for row in rows:
                values = [row[key].replace("|", "\\|") for key in ("source", "status", "target", "rule")]
                print("| " + " | ".join(values) + " |")
        return 0
    if args.command == "inspect":
        source = LegacySource(args.source)
        mapping_errors = validate_mapping(source)
        inventory = source.inventory()
        payload = inventory_payload(inventory)
        if mapping_errors:
            payload["gate"] = {
                "status": "fail",
                "critical_mismatches": len(mapping_errors),
            }
            payload["mapping_errors"] = mapping_errors
        stem = args.stem or (
            f"source-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-"
            f"{inventory.source_sha256[:12]}"
        )
        json_path, markdown_path = write_reports(args.report_dir, stem, payload)
        print(json.dumps({"json": str(json_path), "markdown": str(markdown_path), **payload["gate"]}))
        return 0 if payload["gate"]["status"] == "pass" else 2
    if args.command == "import":
        if not args.dry_run and not args.postgres_dsn:
            parser().error("import requires --postgres-dsn unless --dry-run is used")
        source = LegacySource(args.source)
        options = BridgeOptions(
            source=args.source,
            source_namespace=args.source_namespace,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            resume=not args.no_resume,
            report_dir=args.report_dir,
        )
        target = PostgresTarget(args.postgres_dsn or "")
        if args.dry_run:
            stats, reconciliation = BridgeService(
                options, source, target, snapshot_kind=args.snapshot_kind
            ).run()
        else:
            with target:
                stats, reconciliation = BridgeService(
                    options, source, target, snapshot_kind=args.snapshot_kind
                ).run()
        payload = dict(reconciliation)
        payload["bridge"] = stats.as_dict()
        stem = args.stem or f"import-{args.snapshot_kind}-{str(stats.batch_id)[:12]}"
        json_path, markdown_path = write_reports(args.report_dir, stem, payload)
        result = {
            "json": str(json_path),
            "markdown": str(markdown_path),
            "batch_id": str(stats.batch_id),
            **payload["gate"],
        }
        print(json.dumps(result, sort_keys=True))
        return 0 if payload["gate"]["status"] == "pass" else 2
    raise AssertionError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
