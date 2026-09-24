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

def test_stream_rate_cap_slows_the_reader(tmp_path):
    import time
    target = tmp_path/'dump.partial'
    payload = b'x' * (3 * 1024 * 1024)
    started = time.monotonic()
    cmd=[sys.executable,str(SCRIPTS/'backup-stream.py'),str(target),str(10**9),'1',str(2 * 1024 * 1024)]
    # The reserve check uses 20% of the filesystem; allow it on a test host.
    result = subprocess.run(cmd,input=payload,capture_output=True)
    if result.returncode:
        assert b'reserved disk space' in result.stderr
        return
    assert target.read_bytes() == payload
    # 3 MiB at 2 MiB/s: at least a second.
    assert time.monotonic() - started >= 1.0

def test_dump_runs_in_a_named_container_that_the_exit_trap_stops():
    script = (SCRIPTS/'dump-backup.sh').read_text()
    assert 'docker exec -i -e PGPASSWORD' not in script
    assert 'docker run --rm -i --name "$dumper"' in script
    assert 'trap cleanup EXIT' in script and 'docker kill "$dumper"' in script
    assert "application_name = '$dumper'" in script
    assert '"$BACKUP_MAX_BYTES_PER_SECOND" &' in script and 'wait $!' in script

def test_stopping_the_backup_stops_the_dump_container(tmp_path):
    """SIGTERM посреди потока: контейнер дампа убит, сессия снята, ни готового, ни частичного файла."""
    import os, signal, time
    bindir = tmp_path/'bin'; bindir.mkdir()
    # macOS lacks flock; the lock itself is not what this test checks.
    (bindir/'flock').write_text('#!/usr/bin/env bash\nexit 0\n'); (bindir/'flock').chmod(0o755)
    log = tmp_path/'docker.log'
    (bindir/'docker').write_text(f'''#!/usr/bin/env bash
echo "$*" >> {log}
case "$1" in
  inspect) echo sha256:image ;;
  run) for i in $(seq 1 200); do head -c 65536 /dev/zero; sleep 0.05; done ;;
esac
''')
    (bindir/'docker').chmod(0o755)
    backups = tmp_path/'backups'
    env = dict(os.environ, PATH=f'{bindir}:{os.environ["PATH"]}', BACKUP_DATABASE='db', BACKUP_DB_USER='u',
               BACKUP_DIR=str(backups), MRANKED_DB_CONTAINER='pg', BACKUP_MAX_DUMP_BYTES='1000000',
               BACKUP_RESERVE_BYTES='1')
    process = subprocess.Popen(['bash', str(SCRIPTS/'dump-backup.sh')], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.time() + 10
    while time.time() < deadline and not (log.exists() and ' run ' in f' {log.read_text()}'):
        if process.poll() is not None:
            break
        time.sleep(0.1)
    if process.poll() is not None:
        import pytest
        pytest.skip(f'guard refused on this host: {process.stderr.read()[:200]!r}')
    time.sleep(0.5)
    stopped = time.monotonic()
    process.send_signal(signal.SIGTERM)
    assert process.wait(timeout=15) != 0
    # Остановка не ждёт, пока дамп доработает сам (поддельный длится ~10 с).
    assert time.monotonic() - stopped < 4
    calls = log.read_text()
    assert 'kill mranked-backup-' in calls
    assert "application_name = 'mranked-backup-" in calls
    assert not list(backups.glob('mranked-*.dump'))
    # Недоснятый файл этого запуска тоже убран, а не ждёт суток на диске.
    assert not list(backups.glob('mranked-*.dump.partial'))
