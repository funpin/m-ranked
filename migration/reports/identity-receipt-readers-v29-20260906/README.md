# Identity receipt reader permissions

Focused tests PASS: Python72 (including15 permission cases), Java receipt10 and controller18, plus two real PostgreSQL clean/upgrade lifecycle cases. Private stores remain0700/0400; explicitly provisioned shared stores use2750/0440 with matching writer ownership and inherited reader GID. Existing originals require a fenced metadata-only adoption; their bytes and hashes do not change. Unconverted or unsafe files fail closed.

Commands: `pytest -q tests/test_identity_receipts.py tests/test_identity_history_release_gate.py tests/test_target_collectors.py`; `mvn -Dtest=IdentityCommandEvidenceTest,PublicQueryControllerTest test`; `mvn -Dtest=IdentityCommandPostgresIntegrationTest test` with the same disposable credentials documented in the V29 identity command report. macOS sandboxed execution strips setgid, so permission tests ran unsandboxed on owned temporary directories; no tests were skipped or weakened.

`report.json` binds exact source hashes and unchanged migration schema. Logs are sanitized. The two roundtrip proofs retain actual original-source/receipt hashes and restore validation, not restorable original source bytes. Actual different-UID Linux access acceptance is a separate report under `operations/identity_receipts`; these focused tests alone do not claim cross-UID evidence.
