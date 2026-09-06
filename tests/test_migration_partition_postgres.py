from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from migration.bridge.fixture import build_golden_fixture
from migration.bridge.model import BridgeOptions
from migration.bridge.service import BridgeService
from migration.bridge.source import LegacySource
from migration.bridge.target import PostgresTarget


POSTGRES_DSN = os.environ.get("MRANKED_TEST_POSTGRES_DSN")


@pytest.mark.skipif(not POSTGRES_DSN, reason="requires disposable PostgreSQL")
@pytest.mark.parametrize("batch_size", [2, 100])
def test_partition_preparation_is_bounded_per_month_and_repeated_per_transaction(tmp_path, batch_size):
    source_path = tmp_path / "partition-batches.db"
    build_golden_fixture(source_path)
    calls = {}

    class MeasuredBridge(BridgeService):
        def _import_snapshot_stream(self, stream):
            with patch.object(self.target, "ensure_partition", wraps=self.target.ensure_partition) as prepare:
                super()._import_snapshot_stream(stream)
                calls[stream] = [call.args[0].strftime("%Y-%m") for call in prepare.call_args_list]

    options = BridgeOptions(source_path, f"pytest-partition-batches-{batch_size}", batch_size=batch_size)
    with PostgresTarget(str(POSTGRES_DSN)) as target:
        stats, report = MeasuredBridge(options, LegacySource(source_path), target, snapshot_kind="s0").run()
        assert report["gate"]["status"] == "pass", report["mismatches"]
        # VK/MAX were published in July, Rutube in August. Every month must be
        # prepared even when both months share one batch. Telegram has three
        # July observations: two transactions must each acquire their own lock,
        # but observations within a transaction must not repeat DDL/GRANT work.
        assert calls["platform_snapshots"] == ["2026-07", "2026-08"]
        assert calls["reaction_snapshots"] == ["2026-07"] * (2 if batch_size == 2 else 1)
        assert stats.rows_by_stream["platform_snapshots"] == 3
        assert stats.rows_by_stream["reaction_snapshots"] == 3
