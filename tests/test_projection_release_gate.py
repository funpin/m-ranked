from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess

import pytest


def _gate(payload):
    script=(Path(__file__).resolve().parents[1]/'operations/scripts/cutover-preflight.sh').read_text()
    expression=re.search(r"local projection_filter='(.*?)'\n",script,re.S).group(1)
    return subprocess.run(['jq','-e',expression],input=json.dumps(payload),text=True,capture_output=True).returncode==0


def _valid():
    digest={'rows':1,'distinctKeys':1,'duplicateKeys':0,'sha256':'b'*64}
    proof={'status':'pass','sourceUnchanged':True,'sourceSha256':'a'*64,'datasetRevision':42,
        'asOf':'2026-08-01T12:00:00+00:00','horizons':[24,48,72,168,336],
        'checks':{key:{'status':'pass','expected':digest,'actual':digest} for key in ('overview','periodMetrics','fixedCohort')}}
    return {'gate':{'status':'pass','critical_mismatches':0},'source':{'source_sha256':'a'*64},
        'dataset_revision':42,'projection_verification':proof,
        'checks':[{'check':'derived_projection_parity','status':'pass','critical':True,'details':proof}]}


def test_release_accepts_complete_projection_proof_bound_to_source_and_revision():
    assert _gate(_valid())


@pytest.mark.parametrize('fault',['absent','source','revision','horizon','digest','noncritical','failed'])
def test_release_rejects_missing_partial_stale_or_inconsistent_projection_proof(fault):
    payload=deepcopy(_valid());proof=payload['projection_verification']
    if fault=='absent':del payload['projection_verification']
    elif fault=='source':payload['source']['source_sha256']='c'*64
    elif fault=='revision':payload['dataset_revision']=43
    elif fault=='horizon':proof['horizons']=[72]
    elif fault=='digest':proof['checks']['overview']['actual']={'rows':0,'duplicateKeys':0}
    elif fault=='noncritical':payload['checks'][0]['critical']=False
    elif fault=='failed':proof['status']='fail'
    assert not _gate(payload)
