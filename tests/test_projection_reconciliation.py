from pathlib import Path
import sqlite3

import pytest

from migration.bridge.projection_reconciliation import ReadOnlyLegacyDatabase, _number, verify_projections
from migration.bridge.source import create_online_backup,sha256_file


def test_oracle_numeric_protocol_distinguishes_null_zero_and_exact_large_counter():
    assert _number(None) is None
    assert _number(0) == "0"
    assert _number(9223372036854775807) == "9223372036854775807"
    assert _number(1/3, ratio=True) == "0.33333333"
    with pytest.raises(ValueError, match="non-finite"):
        _number(float("nan"))


def test_original_database_adapter_cannot_write_or_create_sidecars(tmp_path: Path):
    source=tmp_path/'accepted.sqlite'
    with sqlite3.connect(source) as connection:
        connection.execute('CREATE TABLE example(value INTEGER)')
    before=sha256_file(source)
    with ReadOnlyLegacyDatabase(source).connect() as connection:
        with pytest.raises(sqlite3.OperationalError,match='readonly'):
            connection.execute('INSERT INTO example VALUES(1)')
    assert sha256_file(source)==before
    assert sorted(item.name for item in tmp_path.iterdir())==['accepted.sqlite']


def test_oracle_rejects_changed_artifact_before_any_target_query(tmp_path: Path):
    source=tmp_path/'changed.sqlite';source.write_bytes(b'changed')
    with pytest.raises(ValueError,match='SHA-256'):
        verify_projections(source,None,source_name='fixture',expected_sha256='0'*64)


def test_online_backup_closes_connections_and_returns_standalone_artifact(tmp_path: Path):
    from contextlib import closing
    source=tmp_path/'live.sqlite';destination=tmp_path/'frozen.sqlite'
    with closing(sqlite3.connect(source)) as connection:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE example(value INTEGER)')
        connection.execute('INSERT INTO example VALUES(7)');connection.commit()
        report=create_online_backup(source,destination)
        assert report['sha256']==sha256_file(destination)
        assert not any(destination.with_name(destination.name+suffix).exists() for suffix in ('-wal','-shm','-journal'))
        with ReadOnlyLegacyDatabase(destination).connect() as backup:
            assert backup.execute('SELECT value FROM example').fetchone()[0]==7
        # S_final is itself backed up for the rollback SQLite. Reading it through
        # the normal Backup API must not create sidecars or change its SHA.
        rollback=tmp_path/'rollback.sqlite'
        create_online_backup(destination,rollback)
        assert sha256_file(destination)==report['sha256']
        assert not any(destination.with_name(destination.name+suffix).exists() for suffix in ('-wal','-shm','-journal'))
        assert connection.execute('PRAGMA journal_mode').fetchone()[0]=='wal'
        with ReadOnlyLegacyDatabase(rollback).connect() as copied:
            assert copied.execute('SELECT value FROM example').fetchone()[0]==7
