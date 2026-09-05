# SQLite → PostgreSQL bridge

The bridge treats the source SQLite database as immutable. Always create an online
backup first; do not copy a live WAL database with `cp`.

```bash
python -m migration.bridge backup data/reactions.db /safe/path/S0.db
python -m migration.bridge inspect /safe/path/S0.db --report-dir migration/reports
python -m migration.bridge mapping --format markdown
python -m migration.bridge fixture /safe/path/golden.db
python -m migration.bridge fixture /safe/path/golden-catch-up.db --revision 2
python -m migration.bridge import /safe/path/S0.db \
  --source-namespace m-ranked-production \
  --snapshot-kind s0 \
  --dry-run
python -m migration.bridge import /safe/path/S0.db \
  --source-namespace m-ranked-production \
  --snapshot-kind s0 \
  --postgres-dsn 'postgresql://migration_bridge:...@localhost:5432/mranked'
```

`backup` uses the SQLite Backup API, checks `PRAGMA quick_check` and
`foreign_key_check`, writes mode `0600`, and reports SHA-256. `inspect` opens the
backup with `mode=ro&immutable=1`, verifies that every source column has an explicit
mapping decision, and writes matching JSON and Markdown reconciliation artifacts.

Import/catch-up commands intentionally require a PostgreSQL schema that has passed
Flyway smoke checks. Never run a bridge against the live SQLite writer file; use a
verified `S0`/`S-final` backup or a rehearsed change journal input.

The source namespace is migration protocol state: reuse exactly the same value for
S0, catch-up and S-final. The importer generates deterministic UUID/bigint IDs,
persists per-stream checkpoints, rejects identity remapping, and writes matching
JSON/Markdown reconciliation reports. DSNs and raw secrets are never included in
those reports. `--dry-run` performs source integrity and exhaustive mapping gates
without connecting to PostgreSQL.
