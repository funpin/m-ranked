from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import pytest
from collector_target.evidence import ImmutableEvidenceStore, EvidenceUnavailable


def test_evidence_redaction_hash_retry_expiry_and_missing(tmp_path: Path):
    store = ImmutableEvidenceStore(tmp_path / 'raw')
    source = {'access_token': 'never-persist', 'body': 'token=also-secret', 'metrics': {'views': 0, 'shares': None}}
    uri, digest = store.put(source)
    assert store.put(source) == (uri, digest)
    now = datetime.now(timezone.utc)
    value = store.read(uri, digest, purge_after=now+timedelta(days=7), now=now)
    assert value['access_token'] == '[REDACTED]'
    assert value['metrics'] == {'views': 0, 'shares': None}
    path = tmp_path / 'raw' / f'{digest}.json'
    assert b'never-persist' not in path.read_bytes()
    with pytest.raises(EvidenceUnavailable, match='expired'):
        store.read(uri, digest, purge_after=now, now=now)
    path.unlink()
    with pytest.raises(EvidenceUnavailable, match='unavailable'):
        store.read(uri, digest, purge_after=now+timedelta(days=1), now=now)


def test_evidence_corruption_and_symlink_fail_closed(tmp_path: Path):
    store = ImmutableEvidenceStore(tmp_path / 'raw')
    uri, digest = store.put({'views': 1})
    path = tmp_path / 'raw' / f'{digest}.json'
    path.chmod(0o600)
    path.write_text('{"views":2}')
    path.chmod(0o400)
    with pytest.raises(EvidenceUnavailable, match='hash'):
        store.put({'views': 1})
    path.unlink()
    path.symlink_to(tmp_path / 'outside')
    with pytest.raises(EvidenceUnavailable):
        store.put({'views': 1})


def test_precommit_crash_leaves_reusable_object_not_dangling_reference(tmp_path: Path):
    store = ImmutableEvidenceStore(tmp_path / 'raw')
    first = store.put({'metrics': [0, None]})
    # Simulate canonical transaction rollback/process restart after publication.
    restarted = ImmutableEvidenceStore(tmp_path / 'raw')
    assert restarted.put({'metrics': [0, None]}) == first
    assert len(list((tmp_path / 'raw').glob('*.json'))) == 1


class Connection:
    def __init__(self, expiry):
        self.expiry = expiry
        self.last = None
        self.lookups = []
    def transaction(self):
        from contextlib import nullcontext
        return nullcontext()
    def execute(self, sql, params=None):
        if 'max(purge_after)' in sql:
            self.last = self.expiry.get(params[0])
            self.lookups.append(params[0])
        return self
    def fetchone(self):
        return (self.last,)


def test_gc_advances_past_unexpired_across_process_restarts(tmp_path):
    now = datetime.now(timezone.utc)
    root = tmp_path/'raw'
    store = ImmutableEvidenceStore(root)
    first = store.put({'views':1})
    second = store.put({'views':2})
    # Fix worklist order so a retained first object would starve the expired one.
    (root/'.gc-worklist').write_text(first[1]+'.json\n'+second[1]+'.json\n')
    connection = Connection({first[0]: now+timedelta(days=1), second[0]:now-timedelta(days=1)})
    assert store.purge_expired(connection, now=now, max_objects=1) == 0
    assert ImmutableEvidenceStore(root).purge_expired(connection, now=now, max_objects=1) == 1
    assert (root/(first[1]+'.json')).exists()
    assert not (root/(second[1]+'.json')).exists()
    assert len(connection.lookups) == 2


def test_gc_orphan_grace_and_crash_replay(tmp_path):
    now = datetime.now(timezone.utc)
    store = ImmutableEvidenceStore(tmp_path/'raw')
    uri, digest = store.put({'views':3})
    conn = Connection({})
    assert store.purge_expired(conn, now=now, max_objects=1) == 0
    target = store.root/(digest+'.json')
    old = (now-timedelta(days=8)).timestamp()
    os.utime(target, (old,old))
    assert store.purge_expired(conn, now=now, max_objects=1) == 1
    # Recreate stale pre-crash worklist: retry missing object is harmless.
    (store.root/'.gc-worklist').write_text(digest+'.json\n')
    assert store.purge_expired(conn, now=now, max_objects=1) == 0
