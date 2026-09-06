"""Execute generation checks against bounded Linux /proc-shaped fixtures."""
from pathlib import Path
import os
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
HELPER=ROOT/'operations/scripts/nginx-freeze-barrier.sh'


def process(proc,pid,parent,start,binary,role):
    path=proc/str(pid);path.mkdir(parents=True,exist_ok=True)
    fields=['S',str(parent)]+['0']*17+[str(start)]
    (path/'stat').write_text(f'{pid} (nginx) '+ ' '.join(fields)+'\n')
    (path/'cmdline').write_bytes(role.encode()+b'\0')
    if not (path/'exe').exists():(path/'exe').symlink_to(binary)
    return path


def fixture(tmp_path):
    binary=tmp_path/'nginx';binary.write_text('fixture-inode');binary.chmod(0o700)
    proc=tmp_path/'proc';proc.mkdir()
    master=process(proc,101,1,100,binary,'nginx: master process')
    worker=process(proc,202,101,200,binary,'nginx: worker process')
    process(proc,203,101,201,binary,'nginx: cache manager process')
    task=master/'task/101';task.mkdir(parents=True)
    (task/'children').write_text('202 203\n')
    return proc,binary,master,worker


def run(proc,binary,after='',timeout='2'):
    script='''set -Eeuo pipefail
source "$HELPER"
_mranked_nginx_capture_workers "$PROC" "$BINARY" 101
[[ ${#MRANKED_NGINX_OLD_WORKERS[@]} == 1 ]]
'''+after+'''\n_mranked_nginx_wait_workers "$PROC" "$BINARY" "$TIMEOUT"
'''
    return subprocess.run(['/bin/bash','-p','-c',script],env=dict(os.environ,HELPER=str(HELPER),PROC=str(proc),BINARY=str(binary),TIMEOUT=timeout),capture_output=True,text=True)


def test_barrier_waits_for_captured_worker_exit_and_ignores_cache_manager(tmp_path):
    proc,binary,_,_=fixture(tmp_path)
    result=run(proc,binary,'( sleep 0.2; rm "$PROC/202/stat" ) &')
    assert result.returncode==0,result.stderr


def test_reused_pid_is_not_mistaken_for_old_worker(tmp_path):
    proc,binary,_,worker=fixture(tmp_path)
    replacement=worker/'reused';replacement.write_text((worker/'stat').read_text().replace(' 200\n',' 999\n'))
    result=run(proc,binary,'mv "$PROC/202/reused" "$PROC/202/stat"')
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('change',['rm "$PROC/101/stat"','rm "$PROC/101/exe"','mv "$PROC/101/reused" "$PROC/101/stat"'])
def test_changed_or_dead_master_cannot_claim_success_even_when_old_worker_exits(tmp_path,change):
    proc,binary,master,_=fixture(tmp_path)
    (master/'reused').write_text((master/'stat').read_text().replace(' 100\n',' 999\n'))
    result=run(proc,binary,change+'\nrm "$PROC/202/stat"')
    assert result.returncode==75
    assert 'master changed' in result.stderr


def test_timeout_never_kills_or_modifies_old_worker(tmp_path):
    proc,binary,_,worker=fixture(tmp_path)
    before=(worker/'stat').read_bytes()
    result=run(proc,binary,timeout='1')
    assert result.returncode==75 and 'old workers did not exit' in result.stderr
    assert (worker/'stat').read_bytes()==before


@pytest.mark.parametrize('fault',['empty','wrong-parent','wrong-master-exe','wrong-worker-exe'])
def test_capture_rejects_absent_or_unverified_worker_generation(tmp_path,fault):
    proc,binary,master,worker=fixture(tmp_path)
    other=tmp_path/'other';other.write_text('other inode')
    if fault=='empty':(master/'task/101/children').write_text('203\n')
    elif fault=='wrong-parent':(worker/'stat').write_text((worker/'stat').read_text().replace(' S 101 ',' S 999 '))
    else:
        path=(master if fault=='wrong-master-exe' else worker)/'exe'
        path.unlink();path.symlink_to(other)
    assert run(proc,binary).returncode==73


@pytest.mark.parametrize('timeout',['0','-1','121','not-a-number'])
def test_wait_timeout_is_bounded(tmp_path,timeout):
    proc,binary,_,_=fixture(tmp_path)
    assert run(proc,binary,timeout=timeout).returncode==64


def test_failed_generation_barrier_keeps_installed_freeze_and_produces_no_success(tmp_path):
    source=(ROOT/'operations/scripts/switch-routing.sh').read_text()
    start=source.index('mv -- "$new_file" "$NGINX_ACTIVE_ROUTES"')
    end=source.index('\ninstall -d -m 0700 "$ROUTING_REPORT_DIR"',start)
    active=tmp_path/'active';active.write_text('writable-old')
    new=tmp_path/'new';new.write_text('frozen')
    old=tmp_path/'old';old.write_text('writable-old')
    env=dict(os.environ,new_file=str(new),old_file=str(old),NGINX_ACTIVE_ROUTES=str(active),NGINX_BIN='/usr/bin/true',NGINX_CONFIG='fixture',freeze_barrier='true',NGINX_FREEZE_TIMEOUT_SECONDS='1')
    script='set -Eeuo pipefail\nsystemctl() { return 0; }\nmranked_nginx_freeze_wait() { return 75; }\n'+source[start:end]+'\nprintf success'
    result=subprocess.run(['/bin/bash','-p','-c',script],env=env,capture_output=True,text=True)
    assert result.returncode==75 and not result.stdout
    assert active.read_text()=='frozen'
    assert old.read_text()=='writable-old'
    assert source.index('mranked_nginx_freeze_capture "$NGINX_BIN"')<source.index('mv -- "$new_file"')
    assert source.index('mranked_nginx_freeze_wait "$NGINX_BIN"')>source.index('systemctl reload nginx.service')
