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
