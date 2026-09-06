"""Container-only verifier; no host users, permissions or production paths change."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

API, COLLECTOR, REVERSE, BACKUP, OUTSIDER = 23001, 23002, 23003, 23004, 23005
READERS = 25000
ROOT = Path(tempfile.mkdtemp(prefix="mranked-receipts-", dir="/"))
ROOT.chmod(0o755)
CHECKS = []


def child(uid, args, *, expected_success=True, supplemental=()):
    def credentials():
        os.setgroups(list(supplemental))
        os.setgid(uid)
        os.setuid(uid)
        os.umask(0o077)
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, preexec_fn=credentials)
    assert (result.returncode == 0) == expected_success, (uid, args[0], result.returncode, result.stderr)
    return result.stdout.strip()


def python(uid, script, *, expected_success=True, supplemental=()):
    return child(uid, [sys.executable, "-c", script], expected_success=expected_success, supplemental=supplemental)


def java(uid, root, value, *, expected_success=True):
    return child(uid, ["java", "-cp", "/classes", "org.mranked.testing.IdentityReceiptPermissionProbe",
                       str(root), value], expected_success=expected_success)


def provision(path, uid, mode):
    path.mkdir(parents=True, exist_ok=True)
    os.chown(path, uid, READERS if mode == 0o2750 else uid)
    path.chmod(mode)


def info(path):
    value = path.stat()
    return {"uid": value.st_uid, "gid": value.st_gid, "mode": oct(stat.S_IMODE(value.st_mode)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def read(uid, directory, digest, *, success=True, supplemental=()):
    return python(uid, f"from pathlib import Path; from collector_target.identity_evidence import IdentityEvidenceStore; "
                      f"print(IdentityEvidenceStore(Path({str(directory)!r})).read({digest!r}))",
                  expected_success=success, supplemental=supplemental)


def run():
    assert os.geteuid() == 0 and sys.platform == "linux"
    admin = ROOT / "admin"
    collector = ROOT / "collector" / "telegram"
    collector.parent.mkdir()
    collector.parent.chmod(0o755)
    provision(admin, API, 0o700)
    provision(collector, COLLECTOR, 0o700)
    original = '{"action":"account.native_id","target":"fixed-fixture","expected":1,"body":{"nativeId":null}}'
    old_admin = java(API, ROOT, original)
    old_collector = python(COLLECTOR, f"from pathlib import Path; from collector_target.identity_evidence import IdentityEvidenceStore; "
                           f"print(IdentityEvidenceStore(Path({str(collector)!r})).put({{'account': 'fixture', 'nativeId': '-20001'}}))")
    paths = [admin / (old_admin + ".json"), collector / (old_collector + ".json")]
    before = [info(path) for path in paths]
    assert all(item["mode"] == "0o400" for item in before)
    for directory, digest, uid in ((admin, old_admin, API), (collector, old_collector, COLLECTOR)):
        read(uid, directory, digest)
        read(REVERSE, directory, digest, success=False, supplemental=(READERS,))
    CHECKS.append("private0700_0400_owner_only")

    for directory, uid in ((admin, API), (collector, COLLECTOR)):
        os.chown(directory, uid, READERS)
        directory.chmod(0o2750)
    # Changing the directory alone must not silently admit old private files.
    read(REVERSE, admin, old_admin, success=False, supplemental=(READERS,))
    java(API, ROOT, original, expected_success=False)
    CHECKS.append("incomplete_permission_conversion_rejected")
    for path in paths:
        os.chown(path, path.stat().st_uid, READERS)
        path.chmod(0o440)
    after = [info(path) for path in paths]
    assert [(x["uid"], x["sha256"]) for x in before] == [(x["uid"], x["sha256"]) for x in after]
    assert all(item["mode"] == "0o440" and item["gid"] == READERS for item in after)
    assert java(API, ROOT, original) == old_admin
    assert python(COLLECTOR, f"from pathlib import Path; from collector_target.identity_evidence import IdentityEvidenceStore; "
                  f"print(IdentityEvidenceStore(Path({str(collector)!r})).put({{'account': 'fixture', 'nativeId': '-20001'}}))") == old_collector
    CHECKS.append("fenced_metadata_only_adoption_content_and_retry_unchanged")

    new_admin = java(API, ROOT, original.replace('null', '"-20002"'))
    new_collector = python(COLLECTOR, f"from pathlib import Path; from collector_target.identity_evidence import IdentityEvidenceStore; "
                           f"print(IdentityEvidenceStore(Path({str(collector)!r})).put({{'account': 'fixture', 'nativeId': '-20003'}}))")
    objects = [(admin, old_admin, API), (collector, old_collector, COLLECTOR),
               (admin, new_admin, API), (collector, new_collector, COLLECTOR)]
    for directory, digest, uid in objects:
        metadata = info(directory / (digest + ".json"))
        assert metadata["uid"] == uid and metadata["gid"] == READERS and metadata["mode"] == "0o440"
    CHECKS.append("actual_java_and_python_writers_inherit_reader_gid_with_umask0077")

    private_leaf = ROOT / "collector" / "max"
    provision(private_leaf, COLLECTOR, 0o700)
    private_digest = python(COLLECTOR, f"from pathlib import Path; from collector_target.identity_evidence import IdentityEvidenceStore; "
                            f"print(IdentityEvidenceStore(Path({str(private_leaf)!r})).put({{'private': True}}))")
    read(COLLECTOR, private_leaf, private_digest)
    read(REVERSE, private_leaf, private_digest, success=False, supplemental=(READERS,))
    assert info(private_leaf / (private_digest + ".json"))["mode"] == "0o400"
    CHECKS.append("existing_private_and_new_shared_subtrees_coexist_without_implicit_widening")

    identities = {}
    for uid in (API, COLLECTOR, REVERSE, BACKUP, OUTSIDER):
        groups = (READERS,) if uid in (REVERSE, BACKUP) else ()
        identities[str(uid)] = json.loads(python(uid, "import os,json; print(json.dumps({'uid':os.geteuid(),'gid':os.getegid(),'groups':os.getgroups()}))", supplemental=groups))
    assert READERS not in identities[str(API)]["groups"] and READERS not in identities[str(COLLECTOR)]["groups"]
    for uid in (REVERSE, BACKUP):
        for directory, digest, _ in objects:
            read(uid, directory, digest, supplemental=(READERS,))
    CHECKS.append("separate_reverse_and_backup_users_read_both_producers")
    read(API, collector, new_collector, success=False)
    read(COLLECTOR, admin, new_admin, success=False)
    java(COLLECTOR, ROOT, original, expected_success=False)
    CHECKS.append("writers_cannot_read_or_write_each_others_receipts")

    for directory, digest, _ in objects:
        path = directory / (digest + ".json")
        read(OUTSIDER, directory, digest, success=False)
        for uid in (REVERSE, BACKUP):
            for operation in (f"open({str(path)!r},'ab').write(b'x')", f"__import__('os').unlink({str(path)!r})"):
                python(uid, operation, expected_success=False, supplemental=(READERS,))
            python(uid, f"from pathlib import Path; from collector_target.identity_evidence import IdentityEvidenceStore; "
                        f"IdentityEvidenceStore(Path({str(directory)!r})).put({{'forged': True}})",
                   expected_success=False, supplemental=(READERS,))
    CHECKS.extend(["readers_cannot_modify_remove_or_publish", "outsider_cannot_read"])

    for mode in (0o750, 0o2770, 0o2755):
        admin.chmod(mode)
        read(REVERSE, admin, new_admin, success=False, supplemental=(READERS,))
        java(API, ROOT, original, expected_success=False)
    admin.chmod(0o2750)
    CHECKS.append("non_setgid_group_writable_or_public_directories_rejected")
    invalid = admin / (new_admin + ".json")
    invalid.chmod(0o444)
    read(REVERSE, admin, new_admin, success=False, supplemental=(READERS,))
    java(API, ROOT, original.replace('null', '"-20002"'), expected_success=False)
    invalid.chmod(0o440)
    os.chown(invalid, COLLECTOR, READERS)
    read(REVERSE, admin, new_admin, success=False, supplemental=(READERS,))
    os.chown(invalid, API, READERS)
    CHECKS.append("public_or_wrong_owner_objects_rejected")
    os.chown(invalid, API, API)
    read(API, admin, new_admin, success=False)
    java(API, ROOT, original.replace('null', '"-20002"'), expected_success=False)
    os.chown(invalid, API, READERS)
    CHECKS.append("wrong_inherited_gid_rejected_even_for_owner")
    link = ROOT / "linked"
    link.symlink_to(ROOT, target_is_directory=True)
    java(API, link, original, expected_success=False)
    read(REVERSE, link / "admin", new_admin, success=False, supplemental=(READERS,))
    CHECKS.append("symlink_ancestor_rejected_by_both_implementations")
    final = [info(directory / (digest + ".json")) for directory, digest, _ in objects]
    assert [item["sha256"] for item in final[:2]] == [item["sha256"] for item in before]
    assert all(item["mode"] == "0o440" and item["gid"] == READERS for item in final)
    return {"status": "pass", "checks": CHECKS, "identities": identities,
            "beforeAdoption": before, "afterAdoption": after, "finalObjects": final,
            "pythonVersion": sys.version, "system": os.uname().sysname}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
