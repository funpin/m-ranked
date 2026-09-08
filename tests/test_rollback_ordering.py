"""Execute the rollback's actual control body with isolated fake services.

The privileged origin/transition-lock preamble has its own executable guard
suite. This harness runs the unchanged downstream shell body and never touches
real services, routes, credentials or the privileged state directory.
"""
from pathlib import Path
import json
import os
import re
import shlex
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]


def run_rollback(tmp_path,fail=""):
    script=(ROOT/'operations/scripts/rollback.sh').read_text()
    body=script[script.index('# Reads move first'):script.index('state_dir=/var/lib/m-ranked/cutover')]
    route=tmp_path/'route'
    route.write_text('''#!/bin/bash
set -euo pipefail
printf 'route:%s\n' "$2" >>"$EVENTS"
[[ "$FAIL_STEP" != "route:$2" ]] || exit 31
printf '%s' "$2" >"$PHASE"
''')
    reverse=tmp_path/'reverse'
    reverse.write_text('''#!/bin/bash
set -euo pipefail
printf 'reverse:%s\n' "$1" >>"$EVENTS"
[[ "$(cat "$PHASE")" == rollback-freeze ]]
[[ -f "$API_DONE" && -f "$COLLECTORS_DONE" && -f "$WORKER_DONE" ]]
[[ "$FAIL_STEP" != "reverse:$1" ]] || exit 32
''')
    route.chmod(0o700);reverse.chmod(0o700)
    harness='''set -Eeuo pipefail
systemctl() {
  printf 'systemctl:%s\n' "$*" >>"$EVENTS"
  if [[ "$1" == stop && "$2" == m-ranked-target-api.service ]]; then
    [[ "$FAIL_STEP" != stop:api ]] || return 33
    # A blocking service stop cannot return before its accepted work exits.
    printf 'api:inflight-finished\n' >>"$EVENTS"
    : >"$API_DONE"; : >"$COLLECTORS_DONE"
  elif [[ "$1" == stop && "$2" == m-ranked-target-reverse-sync.service ]]; then
    [[ "$FAIL_STEP" != stop:worker ]] || return 34
    : >"$WORKER_DONE"
  elif [[ "$1" == start && "$2" == m-ranked-collector.service ]]; then
    [[ "$(cat "$PHASE")" == legacy ]]
  else
    return 35
  fi
}
curl() {
  printf 'health:legacy\n' >>"$EVENTS"
  [[ "$FAIL_STEP" != health ]]
}
'''+body
    env=dict(os.environ,route_switch=str(route),REVERSE_SYNC_EXECUTABLE=str(reverse),OPERATOR_ID='fixture',CHANGE_TICKET='fixture',
        LEGACY_HEALTH_URL='http://invalid.example.test/health',FAIL_STEP=fail,EVENTS=str(tmp_path/'events'),PHASE=str(tmp_path/'phase'),
        API_DONE=str(tmp_path/'api-done'),COLLECTORS_DONE=str(tmp_path/'collectors-done'),WORKER_DONE=str(tmp_path/'worker-done'))
    (tmp_path/'phase').write_text('writer-freeze')
    result=subprocess.run(['/bin/bash','-p','-c',harness],env=env,capture_output=True,text=True)
    return result,(tmp_path/'events').read_text().splitlines(),(tmp_path/'phase').read_text()


def test_rollback_freezes_writes_and_stops_every_target_writer_before_drain(tmp_path):
    result,events,phase=run_rollback(tmp_path)
    assert result.returncode==0,result.stderr
    assert events==[
        'route:rollback-freeze',
        'systemctl:stop m-ranked-target-api.service m-ranked-target-collector@telegram.service m-ranked-target-collector@vk.service m-ranked-target-collector@max.service m-ranked-target-collector@rutube.service',
        'api:inflight-finished','systemctl:stop m-ranked-target-reverse-sync.service',
        'reverse:drain','reverse:verify','reverse:stop','health:legacy',
        'route:legacy','systemctl:start m-ranked-collector.service']
    assert phase=='legacy'


@pytest.mark.parametrize('failure',['route:rollback-freeze','stop:api','stop:worker','reverse:drain','reverse:verify','reverse:stop','health','route:legacy'])
def test_failed_rollback_never_reopens_admin_or_starts_legacy_writer(tmp_path,failure):
    result,events,phase=run_rollback(tmp_path,failure)
    assert result.returncode!=0
    assert 'systemctl:start m-ranked-collector.service' not in events
    assert phase==('writer-freeze' if failure=='route:rollback-freeze' else 'rollback-freeze')
    if failure!='route:legacy':assert 'route:legacy' not in events


def test_rollback_route_bypasses_forward_preflight_but_preserves_protected_checks():
    source=(ROOT/'operations/scripts/switch-routing.sh').read_text()
    start=source.index('if [[ "$phase" == writer-freeze ]]')
    end=source.index('\nfreeze_barrier=false',start)
    for phase,expected in [('rollback-freeze',''),('legacy',''),('writer-freeze','writer-cutover'),('public-read','public-read')]:
        result=subprocess.run(['/bin/bash','-p','-c','set -Eeuo pipefail\npreflight_call() { printf "%s" "$2"; }\npreflight=preflight_call\n'+source[start:end]],
            env=dict(os.environ,phase=phase),text=True,capture_output=True)
        assert result.returncode==0,result.stderr
        assert result.stdout==expected
    assert 'rollback-freeze) route_file=phase-4-rollback-freeze.conf ;;' in source
    assert source.index('mranked_transition_lock_acquire')<source.index('exec 9>')
    assert '"$source_file" "operations/nginx/routes/$route_file"' in source


def test_writer_report_serializes_the_validated_serving_projection_count(tmp_path):
    source=(ROOT/'operations/scripts/writer-cutover.sh').read_text()
    names=re.findall(r"\('([^']+)'\)",re.search(r'core\(name\) AS \(VALUES(.*?)\n\)',source,re.S)[1])
    assert len(names)==len(set(names))==7
    assert '"$ready_serving_projections" == 7' in source
    start=source.index('jq -n \\\n  --arg status monitoring')
    end=source.index('\nchmod 0600 "$state_file"',start)
    env=dict(os.environ,state_file=str(tmp_path/'state.json'),OPERATOR_ID='fixture',CHANGE_TICKET='fixture',started_at='fixture',
        rollback_deadline='fixture',s_final='fixture',s_final_sha256='0'*64,report_json='fixture',revision_before='1',revision_after='2',published_revision='1',api_dataset_revision='1',ready_serving_projections='7')
    result=subprocess.run(['/bin/bash','-p','-c','set -Eeuo pipefail\n'+source[start:end]],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert json.loads((tmp_path/'state.json').read_text())['readyServingProjections']==len(names)
