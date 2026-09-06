from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess

import pytest


def _gate(payload):
    script=(Path(__file__).resolve().parents[1]/"operations/scripts/cutover-preflight.sh").read_text()
    expression=re.search(r"local identity_history_filter='(.*?)'\n",script,re.S).group(1)
    return subprocess.run(["jq","-e",expression],input=json.dumps(payload),text=True,capture_output=True).returncode == 0


def _valid():
    digest={"rows":2,"distinctKeys":2,"duplicateKeys":0,"sha256":"b"*64}
    proof={"status":"pass","sourceUnchanged":True,"sourceSha256":"a"*64,"datasetRevision":42,
        "asOf":"2026-08-01T12:00:00+00:00",
        "checks":[{"name":key,"status":"pass","expected":digest,"actual":digest} for key in ("native","presentation")]}
    return {"gate":{"status":"pass","critical_mismatches":0},"source":{"source_sha256":"a"*64},
        "dataset_revision":42,"identity_history_verification":proof,
        "checks":[{"check":"canonical_identity_history","status":"pass","critical":True,"details":proof}]}


def test_release_requires_complete_history_proof_bound_to_source_and_revision():
    assert _gate(_valid())


@pytest.mark.parametrize("fault",["absent","source","revision","partial","digest","noncritical","failed","changed"])
def test_release_rejects_missing_partial_stale_or_inconsistent_history_proof(fault):
    payload=deepcopy(_valid());proof=payload["identity_history_verification"]
    if fault=="absent":del payload["identity_history_verification"]
    elif fault=="source":payload["source"]["source_sha256"]="c"*64
    elif fault=="revision":payload["dataset_revision"]=43
    elif fault=="partial":proof["checks"]=proof["checks"][:1]
    elif fault=="digest":proof["checks"][0]["actual"]={"rows":0,"duplicateKeys":0}
    elif fault=="noncritical":payload["checks"][0]["critical"]=False
    elif fault=="failed":proof["status"]="fail"
    elif fault=="changed":proof["sourceUnchanged"]=False
    assert not _gate(payload)


def test_cli_preserves_explicit_historical_artifact_paths():
    from migration.bridge.cli import parser
    args=parser().parse_args(["reconcile","final.sqlite","--source-namespace","example","--snapshot-kind","s_final",
        "--historical-source","s0.sqlite","--historical-source","catchup.sqlite","--verify-identity-history"])
    assert args.historical_source == [Path("s0.sqlite"),Path("catchup.sqlite")]
    assert args.verify_identity_history


def test_writer_passes_explicit_protected_history_artifacts_to_final_import():
    script=(Path(__file__).resolve().parents[1]/"operations/scripts/writer-cutover.sh").read_text()
    assert 'history_bridge_args+=(--historical-source "$historical_source")' in script
    assert '--stem "$report_stem" "${history_bridge_args[@]}"' in script
    assert '"${historical_source%/*}" != "$MIGRATION_SNAPSHOT_DIR"' in script
    assert script.index('historical source metadata is unsafe') < script.index('systemctl stop m-ranked-collector.service')
    assert '.identity_history_verification.status == "pass"' in script


def test_golden_history_source_remains_frozen_when_next_backup_reads_it(tmp_path):
    from migration.bridge.fixture import build_golden_fixture
    from migration.bridge.source import create_online_backup,sha256_file,LegacySource
    prior,current = tmp_path/"s0.sqlite",tmp_path/"catchup.sqlite"
    produced=build_golden_fixture(prior,revision=2)
    accepted_sha=sha256_file(prior)
    assert produced["source_sha256"] == accepted_sha
    with LegacySource(prior).connect() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    create_online_backup(prior,current)
    assert sha256_file(prior) == accepted_sha
    assert all(not Path(str(path)+suffix).exists() for path in (prior,current) for suffix in ("-wal","-shm","-journal"))
