"""Opt-in daily M0 receipt rollup. Never publishes anomaly verdicts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import psycopg


SCRIPT = (Path(__file__).resolve().parents[1] / "research" /
          "smart-engagement-2026-09" / "scripts" / "rollup_m0_daily.py")
PLATFORMS = frozenset({"telegram", "max", "vk", "rutube"})


def _accounts(raw: str) -> tuple[UUID, ...]:
    parts = tuple(part.strip() for part in raw.split(","))
    if any(not part for part in parts):
        raise ValueError("ANOMALY_M0_ACCOUNT_IDS must contain UUIDs")
    try:
        values = tuple(UUID(part) for part in parts)
    except ValueError as error:
        raise ValueError("ANOMALY_M0_ACCOUNT_IDS must contain UUIDs") from error
    if not 1 <= len(values) <= 16 or len(set(values)) != len(values):
        raise ValueError("ANOMALY_M0_ACCOUNT_IDS needs 1–16 distinct accounts")
    return values


def _plan(rows: list[tuple[UUID, str]], accounts: tuple[UUID, ...],
          today: date) -> tuple[tuple[str, tuple[UUID, ...], date, date], ...]:
    by_platform: dict[str, list[UUID]] = defaultdict(list)
    found = set()
    for account_id, platform in rows:
        if account_id not in accounts or platform not in PLATFORMS:
            raise ValueError("M0 account has an unexpected platform or identity")
        found.add(account_id)
        by_platform[platform].append(account_id)
    if found != set(accounts):
        raise ValueError("M0 account is absent from catalog.visible_platform_account")
    # Recompute a bounded rolling window so one missed timer run is recoverable
    # while the seven-day receipts still exist. The rollup is idempotent.
    return tuple((platform, tuple(sorted(ids)), today - timedelta(days=6),
                  today + timedelta(days=1))
                 for platform, ids in sorted(by_platform.items()))


def main() -> None:
    enabled = os.environ.get("ANOMALY_M0_ROLLUP_ENABLED", "false").strip().lower()
    if enabled in {"", "false", "0"}:
        print(json.dumps({"kind": "m0_rollup", "status": "disabled"}))
        return
    if enabled not in {"true", "1"}:
        raise ValueError("ANOMALY_M0_ROLLUP_ENABLED must be true or false")
    accounts = _accounts(os.environ.get("ANOMALY_M0_ACCOUNT_IDS", ""))
    expected_database = os.environ.get("ANOMALY_M0_EXPECTED_DATABASE", "").strip()
    dsn = os.environ.get("ANOMALY_DATABASE_URL", "").strip()
    if not expected_database or not dsn:
        raise ValueError("enabled M0 rollup needs a database URL and expected name")
    max_gap = int(os.environ.get("ANOMALY_M0_MAX_GAP_MINUTES", "60"))
    if not 5 <= max_gap <= 1440:
        raise ValueError("ANOMALY_M0_MAX_GAP_MINUTES must be 5–1440")
    with psycopg.connect(dsn, options="-c default_transaction_read_only=on -c statement_timeout=30000") as connection:
        actual = connection.execute("SELECT current_database()").fetchone()[0]
        if actual != expected_database:
            raise ValueError("M0 rollup database name differs from expected name")
        rows = connection.execute(
            "SELECT id, platform::text FROM catalog.visible_platform_account "
            "WHERE id = ANY(%s::uuid[])", (list(accounts),),
        ).fetchall()
    plan = _plan(rows, accounts, datetime.now(timezone.utc).date())
    if not SCRIPT.is_file():
        raise FileNotFoundError("M0 rollup script is absent from the release")
    for platform, ids, start, end in plan:
        command = [sys.executable, str(SCRIPT), "--platform", platform,
                   "--start", start.isoformat(), "--end", end.isoformat(),
                   "--max-gap-minutes", str(max_gap), "--write",
                   "--expected-database", expected_database]
        for account_id in ids:
            command.extend(("--account", str(account_id)))
        subprocess.run(command, check=True, timeout=600)
    print(json.dumps({"kind": "m0_rollup", "status": "complete",
                      "platforms": [entry[0] for entry in plan],
                      "account_count": len(accounts),
                      "window": [str(plan[0][2]), str(plan[0][3])]}))


if __name__ == "__main__":
    main()
