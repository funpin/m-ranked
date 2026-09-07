"""Delta replay acceptance on a caller-provisioned disposable PostgreSQL DB."""
import os
import sqlite3
from pathlib import Path

import pytest

from migration.bridge.fixture import build_golden_fixture
from migration.bridge.model import BridgeOptions, row_hash
from migration.bridge.service import BridgeService
from migration.bridge.source import LegacySource
from migration.bridge.target import PostgresTarget

DSN = os.environ.get('MRANKED_TEST_POSTGRES_DSN')


@pytest.mark.skipif(not DSN, reason='requires disposable PostgreSQL')
def test_reuse_is_atomic_and_only_changed_or_missing_snapshots_use_writer(tmp_path: Path):
    first, final = tmp_path/'first.db', tmp_path/'final.db'
    build_golden_fixture(first, revision=1)
    build_golden_fixture(final, revision=2)
    namespace = 'pytest-delta-reuse'
    tables = ('platform_snapshots', 'reaction_snapshots')

    def hashes(path):
        with sqlite3.connect(path) as db:
            db.row_factory = sqlite3.Row
            return {(table, int(row['id'])): row_hash(dict(row))
                    for table in tables for row in db.execute('SELECT * FROM '+table)}
    old, new = hashes(first), hashes(final)
    changed = {key for key in new if old.get(key) != new[key]}
    unchanged = set(new) - changed
    assert changed and unchanged

    class Interrupted(BridgeService):
        def _record_revision(self, *args):
            if args[2] == 'platform_snapshots':
                raise RuntimeError('interrupt after reuse before checkpoint')
            return super()._record_revision(*args)

    class Counted(BridgeService):
        imported = set()
        def _import_snapshot(self, stream, row, *args):
            self.imported.add((stream, int(row['id'])))
            return super()._import_snapshot(stream, row, *args)

    with PostgresTarget(DSN) as target:
        initial = BridgeService(BridgeOptions(first, namespace, batch_size=100),
                               LegacySource(first), target, snapshot_kind='s0')
        _, report = initial.run()
        assert report['gate']['status'] == 'pass', report['mismatches']
        options = BridgeOptions(final, namespace, batch_size=100)
        failed = Interrupted(options, LegacySource(final), target, snapshot_kind='catch_up')
        with pytest.raises(RuntimeError, match='interrupt after reuse'):
            failed.run()
        assert target.fetchone('''SELECT count(*) FROM migration.legacy_identity_map
            WHERE last_seen_batch_id=%s AND source_table=ANY(%s)''',
            (failed.batch_id, list(tables))) == (0,)
        assert target.checkpoint(failed.batch_id, 'platform_snapshots')[1] == 0
        resumed = Counted(options, LegacySource(final), target, snapshot_kind='catch_up')
        _, report = resumed.run()
        assert report['gate']['status'] == 'pass', report['mismatches']
        assert resumed.imported == changed
        # All rows, including reused ones, belong to the final verification scope.
        assert target.fetchone('''SELECT count(*) FROM migration.legacy_identity_map
            WHERE last_seen_batch_id=%s AND source_table=ANY(%s)''',
            (resumed.batch_id, list(tables))) == (len(new),)
