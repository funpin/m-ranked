# Cold archive clean-room verification

Verified on 2026-09-03 against a clean V1→V3 Flyway database populated by the
golden-v2 bridge import in PostgreSQL 18.6. The run was archive-only: no
partition or source row was deleted.

## Result

- dataset: `publication_metric_snapshot`
- archive schema: `2`; separate UTC `observed_at`, `collected_at`, and
  `created_at` columns were read back from Parquet
- partition: `[2026-07-01T00:00:00Z, 2026-08-01T00:00:00Z)`
- rows: `7`
- observed range: `2026-07-29T13:00:00Z` through `2026-08-01T11:55:00Z`
- Parquet row groups: `4` with cursor/row-group batch size `2`
- compression: `zstd`
- SHA-256: `830679af8f74f73d80819dd2b24d4669a9276c4e9e501629aacd2fb73d4cd1ec`
- sample rows read and JSON-decoded: `7`
- database manifest: `df6cd893-9dee-47f3-b5b8-d71faccb44cb`, status `verified`
- repeat: reused the same object, checksum and manifest ID
- secret scan (`fixture-secret`, token/cookie/password markers): no matches
- file permissions: Parquet and sidecar both `0600`

## Checks performed before publishing the verified database manifest

1. Fixed versioned Arrow schema and non-secret column whitelist.
2. Bounded server-side PostgreSQL cursor and bounded Arrow row groups.
3. Parquet metadata row-count comparison.
4. Full object SHA-256 calculation.
5. Zstandard codec check for every written column chunk.
6. Bounded sample read, including reaction-breakdown JSON parsing.
7. Observed timestamp min/max comparison.
8. Atomic file and sidecar rename followed by directory `fsync`.

The generated object lived in
`/private/tmp/mranked-archive-v2-clean-20260903` and is test evidence, not an
off-primary production archive. Replication to a separate failure domain and a
production retention DROP remain operational gates.
