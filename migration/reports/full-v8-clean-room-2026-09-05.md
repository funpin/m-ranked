# Full V8 clean-room local verification

This report records engineering evidence from disposable local databases. It
does not approve a production route switch, writer cutover, data deletion, or a
new Flyway migration. It covers the checked-out, uncommitted migration worktree
based on Git commit `a63455cacff18071923a292e1de1bc637f97290f`.

## Environment

- Verification date: `2026-09-05` (`Europe/Moscow`).
- PostgreSQL: `18.6 (Debian 18.6-1.pgdg13+2)` with data checksums enabled by
  the local compose definition.
- Schema under test: exactly eight successful versioned migrations, Flyway
  `V1` through `V8`; no `V9` or repeatable migration was present.
- Primary local database `mranked` was not used as an integration fixture.
- The full-stack database was the disposable `mranked_full_it`.

## Executed evidence

| Layer | Verification | Result |
|---|---|---|
| Flyway | Ordered `flyway.flyway_schema_history` version/script/checksum/success manifest | `V1`–`V8`, all successful, expected frozen checksums |
| Schema | `migration/schema/smoke.sql` | pass; fixture transaction rolled back |
| Activity analytics | `migration/schema/period-activity-golden.sql` | pass; fixture transaction rolled back |
| Comparison analytics | `migration/schema/comparison-golden.sql` | pass; fixture transaction rolled back |
| SQLite → PostgreSQL | `tests/test_migration_bridge_postgres.py` | `1 passed` on the V8 database |
| Cold archive | `tests/test_cold_archive_postgres.py` | `1 passed`; verified Zstandard Parquet plus idempotent manifest reuse |
| Target collectors | `tests/test_target_collectors_postgres.py` | `2 passed` with real PostgreSQL writes and rollback/cleanup contracts |
| Spring backend | full Maven suite with owner, `api_write_admin`, and `api_read` integration credentials, followed by the default regression suite | real-PostgreSQL run: `123 tests`, `0 failures`, `0 errors`, `0 skipped`; final default run: `123 tests`, `0 failures`, `0 errors`, `6 skipped` opt-in PostgreSQL cases |
| Python | full default suite | `390 passed`, `5 skipped`; the five opt-in PostgreSQL cases were exercised in dedicated bridge, cold-archive, collector and reverse-sync runs |
| Next.js | Node 24 `pnpm check` | both typechecks pass, `39/39` tests pass, Next.js 16 production build passes |
| Operational release gates | collector evidence plus transition/deploy focused suite | `78 passed`; strict report/release/symlink binding, trusted artifact/destination chains, hostile-environment rejection, lock contention, nested lock reuse, stale-copy rejection and recovery-path coverage pass |
| Worktree | `git diff --check` | pass |

The Spring real-PostgreSQL run includes the admin mutation/RBAC audit, activity
rating, comparison, overview and detail-fallback integrations. The detail test
proves that an existing institution without period metrics and an existing
publication without an accepted `publication_latest` row no longer become
false 404 responses; nullable counter/quality semantics remain explicit.

The first run on the fresh strict-v3 rehearsal database also exposed a hidden
activity-rating test dependency on an existing dataset revision: SQL
`max(id)` returned `NULL` and could not be mapped as a primitive value. The
test now reads `coalesce(max(id), 0)::bigint`. The focused rerun and the full
real-PostgreSQL suite passed, and their cleanup left the reverse-rehearsal
precondition tables empty.

## Test isolation finding

The verification exposed that the original admin PostgreSQL integration test
committed its unique fixture. Three rows from pre-fix local executions were
already present in the disposable database. The test now owns every inserted
row through unique institution/account/run and correlation UUIDs, restores a
temporarily revoked function grant in `finally`, removes only its own source,
audit, outbox, revision and projection rows in one owner transaction, and
restores the preceding published projection revision.

Two consecutive focused executions and the subsequent full backend run kept
the pre-existing disposable count at `3`, left zero detail/rating revision
markers, restored the previous maximum dataset revision (`118`), and left
`has_function_privilege(api_write_admin,
analytics.rebuild_core_projections(bigint), EXECUTE)=true`.

## Cleanup and release meaning

After the checks, `pg_stat_activity` reported zero sessions for
`mranked_full_it`. That exact database was dropped. A post-drop catalog query
confirmed that `mranked` remained present and `mranked_full_it` did not.

Reverse-sync Writer Gate W has its own four-platform round-trip evidence and
now also has a strict-v3 local report at
`migration/reports/reverse-sync-rehearsal-v8-local-v3.md`. The local report is
deliberately non-approvable; Gate W must still satisfy the machine-enforced
production-like provenance contract for the exact deployed release. Collector
Gate W now rejects the former four-boolean artifact and instead verifies a
fresh protected capture tree against the active deploy, exact V1-V8 manifest,
raw-target `SYMLINKS.sha256` inventory and a separate approval ticket. That
verifier proves artifact integrity and declared invariants, not the truth of
the live provider or SQL observations, which remains an independent review.

Deploy, preflight, routing, writer cutover and rollback now share one fixed,
root-owned transition lock for their complete operation. The inode is
pre-provisioned at boot by a packaged tmpfiles rule; runtime entrypoints never
create, replace, chmod or chown it. Deploy additionally binds `--release-dir`
and its ID to the physical trusted artifact containing the invoked entrypoint,
then rechecks root-owned source/destination inode chains and the complete
executable cohort through staging, Flyway, activation and pass-report
publication. Local hostile-path, hardlink, stale-release, contention,
nested-call and partial-config tests pass. Production rollout must still
validate the Linux host ownership/permissions/flock/tmpfiles setup, and must
prohibit invoking any previously installed entrypoint that predates the guard
because such a copy cannot join the lock retroactively.

CSV and full entity-detail parity still require a separately reviewed additive
schema revision; the frozen V1–V8 target deliberately leaves those legacy
routes on fallback. The modern target CSV service now neutralizes
spreadsheet-formula prefixes before RFC 4180 quoting, while the byte-frozen
legacy `/export/*` contract remains on fallback. Production provider/network
acceptance, visual/performance approval, restore/WAL/standby drills and named
operator approval remain independent release gates.
