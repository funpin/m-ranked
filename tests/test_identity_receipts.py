from pathlib import Path
import hashlib
import json
import os

import pytest

from collector_target.identity_evidence import IdentityEvidenceStore, IdentityEvidenceUnavailable


def test_identity_receipt_is_bounded_immutable_and_retained_without_provider_payload(tmp_path: Path):
    store = IdentityEvidenceStore(tmp_path/"collector"/"max")
    original = {"kind":"collector-account-identity","username":"name","nativeId":None}
    digest = store.put(original)
    path = store.directory/(digest+".json")
    assert path.stat().st_mode & 0o777 == 0o400
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    before = path.stat().st_mtime_ns
    assert store.put(original) == digest and path.stat().st_mtime_ns == before
    assert store.read(digest) == original
    path.chmod(0o600);path.write_text(json.dumps({"username":"forged"}));path.chmod(0o400)
    with pytest.raises(IdentityEvidenceUnavailable,match="HASH_MISMATCH"):
        store.read(digest)
    with pytest.raises(IdentityEvidenceUnavailable,match="HASH_MISMATCH"):
        store.put(original)


def test_receipt_rejects_symlink_large_missing_and_traversal(tmp_path: Path):
    store = IdentityEvidenceStore(tmp_path/"admin")
    digest = store.put({"body":{}})
    path = store.directory/(digest+".json")
    outside=tmp_path/"outside";outside.write_text("{}");path.unlink();path.symlink_to(outside)
    with pytest.raises(IdentityEvidenceUnavailable,match="MISSING"):
        store.read(digest)
    with pytest.raises(IdentityEvidenceUnavailable,match="DIGEST_INVALID"):
        store.read("../outside")
    with pytest.raises(IdentityEvidenceUnavailable,match="TOO_LARGE"):
        store.put({"payload":"x"*131072})


def test_shared_reader_mode_is_explicit_setgid_and_preserves_original_bytes(tmp_path):
    private=IdentityEvidenceStore(tmp_path/"private")
    original={"kind":"collector-account-identity","nativeId":"123"}
    digest=private.put(original)
    path=private.directory/(digest+".json")
    payload=path.read_bytes()
    before=path.stat().st_mtime_ns
    # Adopting existing receipts changes permission metadata only, not their
    # digest, source content or database history. Unconverted files fail closed.
    private.directory.chmod(0o2750)
    with pytest.raises(IdentityEvidenceUnavailable,match="FILE_UNSAFE"):
        private.read(digest)
    path.chmod(0o440)
    assert private.read(digest)==original
    assert private.put(original)==digest
    assert path.read_bytes()==payload and path.stat().st_mtime_ns==before
    new=private.put({"kind":"collector-account-identity","nativeId":"456"})
    new_path=private.directory/(new+".json")
    assert new_path.stat().st_mode & 0o7777==0o440
    assert new_path.stat().st_gid==private.directory.stat().st_gid
    assert new_path.stat().st_uid==private.directory.stat().st_uid
    standalone=IdentityEvidenceStore(tmp_path/"still-private")
    old=standalone.put(original)
    assert standalone.read(old)==original
    assert (standalone.directory/(old+".json")).stat().st_mode & 0o7777==0o400


@pytest.mark.parametrize("mode",[0o750,0o755,0o770,0o2770,0o2755,0o2700,0o1700])
def test_group_access_never_accepts_unprovisioned_or_writable_directories(tmp_path,mode):
    store=IdentityEvidenceStore(tmp_path/"admin")
    digest=store.put({"body":{}})
    store.directory.chmod(mode)
    with pytest.raises(IdentityEvidenceUnavailable,match="DIRECTORY_UNSAFE"):
        store.read(digest)
    with pytest.raises(IdentityEvidenceUnavailable,match="DIRECTORY_UNSAFE"):
        store.put({"body":{}})


@pytest.mark.parametrize("mode",[0o400,0o444,0o460,0o640,0o2440])
def test_shared_directory_rejects_incompatible_object_permissions(tmp_path,mode):
    directory=tmp_path/"admin";directory.mkdir();directory.chmod(0o2750)
    store=IdentityEvidenceStore(directory)
    digest=store.put({"body":{}})
    (directory/(digest+".json")).chmod(mode)
    with pytest.raises(IdentityEvidenceUnavailable,match="FILE_UNSAFE"):
        store.read(digest)
