from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .model import MonthRange
from .service import ColdArchiveService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mranked-cold-archive",
        description="Export and verify one M-Ranked snapshot partition.",
    )
    parser.add_argument("--dsn", required=True, help="maintenance PostgreSQL DSN")
    parser.add_argument("--month", required=True, help="partition month, YYYY-MM")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--batch-size", type=int, default=5_000)
    parser.add_argument("--min-free-bytes", type=int, default=256 * 1024 * 1024)
    parser.add_argument(
        "--drop-hot-partition",
        action="store_true",
        help="invoke the database retention gate after archive verification",
    )
    parser.add_argument(
        "--confirm",
        help="must equal DROP_HOT_PARTITION when --drop-hot-partition is used",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        result = ColdArchiveService(
            arguments.dsn,
            arguments.output_dir,
            batch_size=arguments.batch_size,
            min_free_bytes=arguments.min_free_bytes,
        ).archive(
            MonthRange.parse(arguments.month),
            drop_hot_partition=arguments.drop_hot_partition,
            drop_confirmation=arguments.confirm,
        )
    except Exception as error:
        # The DSN is intentionally never echoed. psycopg messages are reduced to
        # their type here; operators use structured server logs for detail.
        print(
            json.dumps(
                {"status": "failed", "errorCode": type(error).__name__},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"status": "verified", **result.as_dict()}, sort_keys=True))
    return 0
