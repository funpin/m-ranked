"""Rehearsal scope guards; full real HTTP verification is the opt-in reverse test."""
import pytest

from operations.http_transition.verifier import local_database


def test_provided_jar_is_copied_exactly_and_source_changes_rejected(tmp_path):
    import hashlib
    from operations.http_transition.rehearse import stage_jar, verify_jar_binding
    original, copy = tmp_path / "source.jar", tmp_path / "executed.jar"
    original.write_bytes(b"original jar fixture")
    binding = stage_jar(original, copy)
    assert binding["sha256"] == hashlib.sha256(original.read_bytes()).hexdigest()
    assert copy.read_bytes() == original.read_bytes()
    verify_jar_binding(binding)
    original.write_bytes(b"different jar fixture")
    with pytest.raises(ValueError, match="changed"):
        verify_jar_binding(binding)


def test_provided_jar_rejects_symlink_and_non_regular_inputs(tmp_path):
    from operations.http_transition.rehearse import jar_sha256
    original = tmp_path / "source.jar"
    original.write_bytes(b"fixture")
    link = tmp_path / "link.jar"
    link.symlink_to(original)
    with pytest.raises(OSError): jar_sha256(link)
    with pytest.raises((OSError, ValueError)): jar_sha256(tmp_path)


@pytest.mark.parametrize("dsn", [
    "host=production.example dbname=example_it user=postgres",
    "host=127.0.0.1 dbname=mranked user=postgres",
    "host=/var/run/postgresql dbname=example_it user=postgres",
    "dbname=example_it user=postgres",
    "host=localhost dbname=example_IT user=postgres",
    "host=localhost dbname='test_it;DROP DATABASE example' user=postgres",
])
def test_scope_rejects_implicit_remote_or_non_disposable_database(dsn):
    with pytest.raises(ValueError, match="explicit loopback"):
        local_database(dsn)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_scope_accepts_explicit_local_disposable_database(host):
    result = local_database(f"host={host} port=54329 dbname=own_http_it user=collector_ingest")
    assert result["dbname"] == "own_http_it" and result["port"] == "54329"


def test_failed_junit_tracebacks_redact_generated_credentials(tmp_path):
    from operations.http_transition.rehearse import redact_evidence
    evidence = tmp_path / "failure.xml"
    evidence.write_text('<failure>connection password=synthetic-secret</failure>')
    redact_evidence(tmp_path, ["synthetic-secret"])
    assert evidence.read_text() == '<failure>connection password=[redacted]</failure>'


@pytest.mark.parametrize("fault", ["none", "missing_history", "missing_projection", "failed", "changed_source", "different_source", "different_revision", "bool_revision"])
def test_final_http_evidence_requires_both_independent_s_final_proofs(fault):
    from copy import deepcopy
    from operations.http_transition.rehearse import require_s_final_evidence
    proof = {"status": "pass", "sourceUnchanged": True, "sourceSha256": "a" * 64, "datasetRevision": 42}
    final = {"gate": "pass", "sourceSha256": "a" * 64,
             "identityHistoryVerification": deepcopy(proof), "projectionVerification": deepcopy(proof)}
    if fault == "missing_history": del final["identityHistoryVerification"]
    elif fault == "missing_projection": del final["projectionVerification"]
    elif fault == "failed": final["identityHistoryVerification"]["status"] = "fail"
    elif fault == "changed_source": final["projectionVerification"]["sourceUnchanged"] = False
    elif fault == "different_source": final["projectionVerification"]["sourceSha256"] = "b" * 64
    elif fault == "different_revision": final["projectionVerification"]["datasetRevision"] = 43
    elif fault == "bool_revision": final["identityHistoryVerification"]["datasetRevision"] = True
    if fault == "none":
        assert require_s_final_evidence({"sFinal": final}) == final
    else:
        with pytest.raises(ValueError, match="required S-final"):
            require_s_final_evidence({"sFinal": final})


@pytest.mark.parametrize("fault",["none","missing","old_source","old_batch","nonzero","revision","missing_history"])
def test_http_round_trip_requires_a_new_second_s_final_and_exact_repeat(fault):
    from copy import deepcopy
    from operations.http_transition.rehearse import require_second_s_final_evidence
    proof={"status":"pass","sourceUnchanged":True,"sourceSha256":"a"*64,"datasetRevision":42}
    first={"gate":"pass","batchId":"first","sourceSha256":"a"*64,
        "identityHistoryVerification":deepcopy(proof),"projectionVerification":deepcopy(proof)}
    second=deepcopy(first)
    second.update(batchId="second",sourceSha256="b"*64)
    for key in ("identityHistoryVerification","projectionVerification"):
        second[key].update(sourceSha256="b"*64,datasetRevision=45)
    second["repeat"]={"gate":"pass","batchId":"second","rowsWritten":0,"datasetRevisionBefore":45,"datasetRevisionAfter":45}
    reverse={"sFinal":first,"secondSFinal":second}
    if fault=="missing": del reverse["secondSFinal"]
    elif fault=="old_source":
        second["sourceSha256"]="a"*64
        for key in ("identityHistoryVerification","projectionVerification"):second[key]["sourceSha256"]="a"*64
    elif fault=="old_batch":second["batchId"]="first"
    elif fault=="nonzero":second["repeat"]["rowsWritten"]=1
    elif fault=="revision":second["repeat"]["datasetRevisionAfter"]=46
    elif fault=="missing_history":del second["identityHistoryVerification"]
    if fault=="none":assert require_second_s_final_evidence(reverse)==second
    else:
        with pytest.raises(ValueError):require_second_s_final_evidence(reverse)
