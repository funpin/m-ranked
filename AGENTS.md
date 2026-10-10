# Repository agent instructions

## Production access is not recorded here

This repository is public. Host addresses, SSH ports, service endpoints and any
other operational access details belong in the operator's local notes, never in
a tracked file. A previous revision recorded them here and the history had to be
rewritten; gitleaks does not catch an address, so nothing but this rule stands
between the next such note and another public disclosure.

## No regressions in speed or functionality

Every change and every new feature must keep page response times, system
throughput and resource use (CPU, memory, disk) no worse than before, and must
not break or remove existing functionality. Improving these parameters is
welcome; making any of them worse is not acceptable.

- Measure before and after on production-sized data, not only on fixtures:
  page p50/p95 (cold and warm), the SQL behind the touched readers, and the CPU
  and memory of the affected services. A plan that is fine on a small test
  database can scan whole tables on production.
- Size every cache, buffer and limit against the memory limit of the service
  that holds it, with headroom for allocator overhead. On 2026-10-10 the Redis
  response cache had a data budget equal to its service limit: Redis stalled
  60% of the time, CPU rose several times over and page p95 climbed.
- If a change cannot avoid a regression, do not ship it as is: rework it, or
  bring the measured trade-off to the owner before deploying.

## Database decision: CSV export retired

- Decision owner: `funpin`; recorded on 2026-09-21. CSV export, its API/frontend/admin routes, background jobs, spool configuration, and collector-side CSV materialization are retired product behavior.
- Migration `db/migrations/0033_remove_csv_exports.sql` removes `analytics.legacy_native_export_lexeme`. The table duplicated every metric snapshot, was no longer read by the application, and consumed about 6 GB in production, accelerating disk growth.
- The same rollout corrected `0028_publication_latest_batch_revision.sql`: the ingestion finalizer authorizes membership in the `collector_ingest` capability role and grants execution only to that role. Production platform logins such as `collector_telegram` and `collector_rutube` are members rather than direct `collector_ingest` sessions.
- Treat this removal as an intentional compatibility boundary. Keep collectors writing only the live analytics model, and keep public, legacy, and administrative CSV surfaces absent. Parquet cold archives are a separate retention mechanism.
- For database or deployment work touching this boundary, read the CSV-export sections in `docs/OPERATIONS.md` and `operations/runbooks/DEPLOY.md`; migration `0033` has a collector-stop ordering requirement.

## Storage operations handoff

For disk, backup, retention or release-GC work, read
[STORAGE_BUDGET.md](operations/runbooks/STORAGE_BUDGET.md) first. It records the
measured budget, prepared-versus-deployed status, approval boundaries and the
unresolved delivery coverage/product retention decisions. Reuse multiplexed
SSH; preserve key-only authentication and fail2ban.
