"""Validate actual rehearsal protocol evidence with the deployment JQ predicate.

This does not grant deployment approval or promote local evidence to production.
Only the external provenance comparisons are disabled; no input JSON is changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def verify(path: Path, *, root: Path | None = None) -> dict:
    root = root or Path(__file__).resolve().parents[2]
    path = path.resolve(strict=True)
    before = path.read_bytes()
    script = root / "operations/scripts/cutover-preflight.sh"
    source = script.read_text()
    function = source.split("check_reverse_sync_rehearsal_gate() {", 1)[1].split("check_collector_parity_gate() {", 1)[0]
    match = re.search(r"local contract_filter='(?P<filter>.*?)'\n  if jq -e", function, re.DOTALL)
    if not match or "--argjson protocolOnly false" not in function:
        raise RuntimeError("the production preflight must explicitly disable protocol-only mode")
    command = ["jq", "-e", "--argjson", "protocolOnly", "true"]
    for key in (
        "releaseId", "manifestSha256", "sourceNamespace", "approvalTicket",
        "operator", "finalSchemaSha256", "transitionSha256",
    ):
        command += ["--arg", key, ""]
    result = subprocess.run(command + [match["filter"]], input=before, capture_output=True, timeout=30)
    unchanged = path.read_bytes() == before
    return {"status": "pass" if result.returncode == 0 and unchanged else "fail",
            "scope": "actual-rehearsal-protocol", "productionAcceptance": False,
            "externalReleaseAndOperatorApprovalVerified": False,
            "inputUnchanged": unchanged, "inputSha256": hashlib.sha256(before).hexdigest(),
            "predicateSha256": hashlib.sha256(match["filter"].encode()).hexdigest(),
            "preflightScriptSha256": hashlib.sha256(script.read_bytes()).hexdigest(),
            "validatorExitCode": result.returncode,
            "validationError": ("JQ_SCHEMA_ERROR" if result.returncode > 1 else "PROTOCOL_REJECTED") if result.returncode else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.report)
    payload = (json.dumps(result, indent=2) + "\n").encode()
    with args.output.open("xb") as stream: stream.write(payload)
    with Path(str(args.output)+".sha256").open("x") as stream:
        stream.write(hashlib.sha256(payload).hexdigest()+"  "+args.output.name+"\n")
    print(json.dumps(result))
    raise SystemExit(0 if result["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
