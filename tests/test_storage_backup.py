import hashlib
import json
from pathlib import Path
import subprocess
import sys

SCRIPTS = Path(__file__).parents[1]/'operations/scripts'

def test_stream_size_cap_never_overwrites_existing_file(tmp_path):
    target = tmp_path/'dump.partial'
    cmd=[sys.executable,str(SCRIPTS/'backup-stream.py'),str(target),'10','1']
    assert subprocess.run(cmd,input=b'01234567890',capture_output=True).returncode != 0
    assert target.stat().st_size == 0
    target.write_bytes(b'protected')
    assert subprocess.run(cmd,input=b'new',capture_output=True).returncode != 0
    assert target.read_bytes() == b'protected'

def test_rotation_keeps_verified_and_newest_until_new_restore(tmp_path):
    old=tmp_path/'mranked-20260921T010000Z.dump'
    middle=tmp_path/'mranked-20260922T010000Z.dump'
    new=tmp_path/'mranked-20260923T010000Z.dump'
    for f in [old,middle,new]:f.write_bytes(f.name.encode())
    cmd=[sys.executable,str(SCRIPTS/'rotate-dumps.py'),str(tmp_path),'1']
    assert subprocess.run(cmd,capture_output=True).returncode == 75
    assert all(f.exists() for f in [old,middle,new])
    def receipt(f):
        f.with_suffix('.restore-verified.json').write_text(json.dumps(dict(dump=f.name,restore_exit_code=0,sha256=hashlib.sha256(f.read_bytes()).hexdigest())))
    receipt(old)
    assert subprocess.run(cmd,capture_output=True).returncode == 0
    assert old.exists() and new.exists() and not middle.exists()
    receipt(new)
    new.write_bytes(b'corrupted')
    assert subprocess.run(cmd,capture_output=True).returncode != 0
    assert old.exists()
    new.write_bytes(new.name.encode());receipt(new)
    assert subprocess.run(cmd,capture_output=True).returncode == 0
    assert new.exists() and not old.exists()
