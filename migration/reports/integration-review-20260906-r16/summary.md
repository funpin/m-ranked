# r16 incomplete integration evidence

FAIL: 32 commands completed; Python failed, cleanup passed. Sum of recorded command durations is 321.580 seconds, not a reconstructed wall-clock duration. No production acceptance is claimed.

Completed mandatory service suites passed 121 cases with zero skips. `reverse-rehearsal` was never executed. Spring ran 224 cases: 220 passed, four conditional MigrationInstallation entry points skipped; the separate query-plan case passed. Sanitized XML and source/retained hashes are available in `spring-junit`.

Python: 561 passed, 1 failed, 108 conditional skips, 45.79 seconds. Only 107 of108 conditional service cases have successful mandatory-service XML in this run; the actual reverse integration case is unexecuted. The coverage map explicitly records this gap.

The failure was the rollback preflight test's earlier extraction boundary (`active_dir`) reading a concurrently updated routing file and including new barrier setup without `script_dir`. The harness now stops at `freeze_barrier=false`; separate generation tests cover the new block. Current targeted tests passed, but r16 remains failed and incomplete.

Actual installer logs show V29 completion. No terminal reverse/database migration manifest exists for this run, and no schema inventory is attributed to run start. Exact commands, durations, per-suite counts and retained proof hashes are in `summary.json`.
