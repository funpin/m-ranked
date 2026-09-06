# V29 monotonic native identity regression

PASS on isolated PostgreSQL databases. Both actual Flyway clean V1–V29 and populated V28→V29 cases use the real Java catalog command producer, original collector receipts, reverse sync, second required S_final, and a fresh no-op repeat. The upgrade case proves the old defect in a rolled-back transaction, then checks exact preservation of existing rows. Older/equal provider times fail atomically and record failure; the next valid provider time is accepted unchanged.

`report.json` contains exact migration hashes, test counts and source-file hashes. The two roundtrip proofs include complete history/source-artifact digests and receipt restore inventories. `collector-and-history-proof.json` retains the existing independent tamper checks. These are self-contained results/hashes, **not a source backup**; original synthetic SQLite/receipt bytes lived in deleted disposable directories. Reproduce them with `migration/integration/identity_command_fixture.py` and the Java test.

Commands (with disposable DB credentials supplied through the documented test environment):

```sh
mvn -Dtest=IdentityCommandPostgresIntegrationTest,IdentityCommandEvidenceTest,PublicQueryControllerTest test
pytest -q tests/test_identity_receipts.py tests/test_identity_history_release_gate.py tests/test_target_collectors.py
pytest -q tests/test_identity_history_postgres.py
```

The final two-case Java rerun adds explicit failed collection-result assertions; evidence and controller tests passed in the immediately preceding focused run. Required environment names are `MRANKED_EXPORT_TEST_ADMIN_URL`, `_USERNAME`, `_PASSWORD`, `MRANKED_ADMIN_TEST_PASSWORD`, `MRANKED_LEGACY_CSV_BRIDGE_PASSWORD`, and `MRANKED_LEGACY_CSV_COLLECTOR_PASSWORD`. `MRANKED_IDENTITY_COMMAND_PROOF` optionally retains fresh proof plus a `-upgrade-v28.json` sibling. Local bootstrap authority creates and drops only UUID-named test databases. The mandatory integration runner already supplies these inputs.

No production operations were performed. Full V29 integration and HTTP acceptance are separate gates; V28 r14 remains historical baseline evidence.
