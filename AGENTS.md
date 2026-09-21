# Repository agent instructions

@/Users/funpin/.codex/RTK.md

## Database decision: CSV export retired

- Decision owner: `funpin`; recorded on 2026-09-21. CSV export, its API/frontend/admin routes, background jobs, spool configuration, and collector-side CSV materialization are retired product behavior.
- Migration `db/migrations/0029_remove_csv_exports.sql` removes `analytics.legacy_native_export_lexeme`. The table duplicated every metric snapshot, was no longer read by the application, and consumed about 6 GB in production, accelerating disk growth.
- The same rollout corrected `0028_publication_latest_batch_revision.sql`: the ingestion finalizer authorizes membership in the `collector_ingest` capability role and grants execution only to that role. Production platform logins such as `collector_telegram` and `collector_rutube` are members rather than direct `collector_ingest` sessions.
- Treat this removal as an intentional compatibility boundary. Keep collectors writing only the live analytics model, and keep public, legacy, and administrative CSV surfaces absent. Parquet cold archives are a separate retention mechanism.
- For database or deployment work touching this boundary, read the CSV-export sections in `docs/OPERATIONS.md` and `operations/runbooks/DEPLOY.md`; migration `0029` has a collector-stop ordering requirement.
