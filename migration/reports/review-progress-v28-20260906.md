# Migration review checkpoint, 2026-09-06

This is an intermediate checkpoint, not a completed migration or release approval.
HEAD remains `a7a2f09ff156eb72445f04f40dbe0e93d3378911`; original V1–V8 bytes are unchanged.
V1–V28 are frozen. Writer Gate W is CLOSED and production remains on legacy.

## Verified at this checkpoint

- [Mandatory integration r14](integration-review-20260906-r14/integration.json):
  all 33 commands successful, including fresh PostgreSQL/Redis, clean install,
  V8 upgrade, bridge, collectors, archive, Java, Python, reverse and cleanup;
  sum of command durations 396.012 seconds. Retained Spring JUnit including the
  separate query-plan test: 216 cases, zero failures/errors, four conditional
  migration entrypoints skipped in the broad invocation; the installation
  entrypoints were executed explicitly by earlier mandatory commands.
- [Actual Java identity round trip](identity-command-v28-20260906/README.md):
  original command input → reverse → second required S_final → zero-write repeat;
  original receipts restored into a separate directory while the original is
  unavailable. Complete independent reconciliation succeeds; missing/corrupt
  restored receipts fail closed. These reports are test results and hashes, not
  an independently restorable production backup.
- [Final-code V28 representative oracle](representative-frozen-v28-r2/verification.json):
  R30, zero critical mismatches, 150.530276 seconds. 207 institutions, 824 accounts,
  824 publications, 9,026 observations, 3,308 overview rows, 19,776 period cells,
  and 1,611,604 fixed-cohort result rows; exact source/actual-target digests agree.
- [All overview cards](../../frontend/evidence/overview-semantic-v28-r1/report.json):
  4,136 rendered cards over 20 platform/period combinations and every continuation
  page. Exact title, legacy link, status text and status class PASS.
- [Authenticated browser forms](../../frontend/evidence/manage-flow-v28-r2/report.json):
  14/14 on the separate forms database; includes real writes/readback, stable
  CSRF, roles, optimistic conflicts, four-platform matrix, native ID, deletion
  cancellation/confirmation and explicit unavailable MRating error.
- [V28 visual r1](../../frontend/evidence/visual-full-v28-r1/report.json):
  176/176, no masks, exact status checks, max raw pixel difference 0.2938271605%.
  This capture precedes the final receipt-directory fsync package; another
  capture against that package is underway. Future V29 acceptance remains open.
- [Production browser contracts](../../frontend/test-results/routes-production-v28-r1.json):
  48/48. Frontend lint, typecheck, generated-client drift and 90 unit cases PASS.
  Initial-JS bundle diagnostics pass, but final quiet-host mobile measurements
  have not run and are not replaced by the bundle diagnostic.
- [V28 physical DR](../../operations/disaster_recovery/evidence/local-v28-final-r1/dr-9c1f082d57a5.json):
  all 12 checks PASS, own resources removed. Standby RTO 7.1508 s / controlled
  RPO 0; full restore 28.3266 s; PITR 35.3363 s / controlled RPO 0.662529 s.
  This is one-host synthetic physical rehearsal, not remote production acceptance.

## New finding that remains open

The expanded real HTTP round trip caught a V16 native-history timestamp defect:
after a collector observation ahead of the application clock, an administrator
can clear and re-enroll a native identity with a start time before the previous
closed interval. The insert considers only
active rows, so after clearing it can start before the previous closed interval.
V29 is being prepared to respect the last boundary across the complete native
timeline. Collector re-enrollment also must reject an observation at or before
the closed boundary without changing the original observation timestamp.
The failing HTTP artifacts remain preserved; tests and fixture clocks are not
being weakened to make this scenario pass.

The real HTTP fixture also exposed inherited CONNECT permission through api_read;
its disposable read login now keeps reads available while the separate collector
and administrative writer connections are fenced. The schema of the reverse
rehearsal report is v4 (the journal remains v3). Production preflight now requires
both S_final proofs, exact no-op replay, original receipt failure cases and actual
HTTP/writer evidence. Validation of the final genuine HTTP artifact is pending.

The missing-delta chart tooltip still awaits the owner's choice: legacy renders
`0`, the target renders `—`, while the underlying data remain NULL. Neither pixel
tolerance nor this checkpoint constitutes approval of that display deviation.

Remaining work: V29 implementation/actual regression and clean-upgrade gate,
final genuine HTTP round trip plus protocol validation, final runtime evidence,
visual/chart capture, quiet mobile/API measurements and the consolidated report.
Production credentials, live-provider/remote-storage acceptance and explicit
production transition approvals remain external requirements.
