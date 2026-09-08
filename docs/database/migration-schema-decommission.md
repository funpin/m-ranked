# Migration schema decommission rehearsal

Status: **rehearsed on a disposable schema-only production copy; not executed
in production**. Owner: database operator. Production use is prohibited until
a separate approval is granted from production-shaped restored-copy evidence.
This work is deliberately independent from the publisher/storage rollout.

## Dependency classification

| Object or consumer | Classification before the final contract | Disposition |
|---|---|---|
| `migration.import_batch`, `checkpoint`, `reconciliation_result` | completed bridge/reconciliation audit | export in recovery pack; no runtime replacement |
| `migration.legacy_identity_map`, `identity_map_history` | bridge identity and immutable recovery evidence | export and checksum; current routing remains in `catalog.legacy_entity_alias` |
| `migration.legacy_evidence`, preservation/disappearance tables | immutable recovery/audit evidence | export and checksum; no hot runtime copy |
| `migration.legacy_export_lexeme` | retired SQLite-compatible CSV generation | retire export function and preserve existing generated artifacts only |
| serving projection legacy-error CTE | runtime dependency | the final contract replaces it with canonical collection-result semantics |
| publication-content refresh | historical bootstrap dependency | the final contract preserves archived canonical content and removes bridge reads |
| official-rating context | runtime dependency | the final contract persists `entity_scope` in `rating.official_rating_observation` |
| history reaction decoration | historical bootstrap dependency | the final contract derives from canonical `reaction_breakdown` |
| `ops_and_admin.legacy_account_presentation` | admin runtime dependency | the final contract derives access/error presentation from canonical account/results |
| `migration.bridge`, reverse-sync, reconciliation commands and their tests | recovery/transition tooling | archive with the recovery pack; never start after schema removal |
| existing `flyway.flyway_schema_history` | inert production bootstrap audit | no runtime reader; may be exported before a separately approved schema cleanup |
| `catalog.legacy_entity_alias` | canonical legacy-ID runtime mapping | protected and verified before/after rehearsal |

The source inventory includes application code, SQL migrations/functions/views,
grants, systemd units, operational scripts, runbooks, bridge/reconciliation
modules and tests. PostgreSQL catalog inventory (`pg_depend` plus function-text
inspection) must be captured from the restored production-shaped copy because a
source scan cannot prove the live catalog state.

## Recovery pack

Store the pack outside Git in the approved encrypted backup repository. Use a
new immutable directory named by database, UTC timestamp, source backup ID and
change ticket. It contains:

- source SQLite snapshot and its existing manifest;
- custom-format PostgreSQL dumps of schema `migration` and table
  `catalog.legacy_entity_alias`;
- deterministic CSV exports of `migration.legacy_identity_map`,
  `migration.identity_map_history`, `migration.import_batch`, reconciliation
  and preservation/evidence tables;
- `pg_dump --schema-only` output, existing bootstrap-history export, object/grant/dependency
  inventory, reconciliation reports and the restored-copy test report;
- `SHA256SUMS`, byte counts, database/server/schema-contract identity, operator and ticket.

Generate exports with `psql --no-psqlrc --set ON_ERROR_STOP=1` and ordered
`COPY (SELECT ...) TO STDOUT WITH (FORMAT csv, HEADER true)`. Do not place a
password in commands or reports. After all files are closed, generate
`SHA256SUMS`, verify it from a second process, make the pack read-only, upload it
to protected storage, and verify the remote copy. Record only the storage
object ID, retention policy and checksum manifest in the approval evidence.

Recovery proof restores both schema dumps into a fresh database, compares every
export row count and SHA-256, validates the final schema contract, resolves a
sample of legacy IDs through `catalog.legacy_entity_alias`, and reruns the
bridge reconciliation in read-only mode.

## Disposable-copy rehearsal

1. Restore a current production backup to a database whose name ends in
   `_restore`, `_rehearsal`, or `_disposable`; keep networking/routes isolated.
2. Apply `transition-production-to-final.sql` over a restore of the observed production schema and validate the final contract.
3. Stop/disable reverse-sync and all bridge/import writers. Build and remotely
   verify the recovery pack above.
4. Capture `pg_depend`, view, function, trigger, grant and source-code inventory.
5. Run
   [`decommission-migration-schema-on-restored-copy.sql`](../../operations/sql/decommission-migration-schema-on-restored-copy.sql)
   with `PGOPTIONS='-c mranked.allow_disposable_migration_drop=true'`. The patch
   uses `RESTRICT`, checks the database name and refuses remaining dependencies.
6. Restart backend, web, the explicit oneshot publisher and all four collectors.
   Run API/UI smoke, legacy-ID lookup, collector transaction/replay, outbox,
   readiness/freshness, publication history and publisher failure/restart tests.
7. Perform a second restore using only the recovery pack and repeat checksum,
   alias and reconciliation checks.
8. Save sanitized outputs, timings, row/byte/WAL/temp deltas and rollback result.

Rollback in rehearsal is database replacement: stop processes, discard the
copy, restore the original backup, validate the schema contract and checksums, and rerun
smoke tests. Do not attempt to reconstruct immutable evidence manually.

## Production decision gate

No production drop is part of schema installation or normal deploy. Approval
requires a successful production-shaped rehearsal, verified remote recovery
pack, zero external dependencies, explicit retirement of reverse-sync/bridge
operations, product sign-off for obsolete legacy CSV behavior, and a scheduled
rollback window. Until then `migration.*` remains intact and consumes only its
existing storage; the final contract removes it from hot serving paths.
