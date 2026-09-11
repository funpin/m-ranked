# Archived SQLite-to-PostgreSQL rehearsals

This directory contains historical import/reconciliation fixtures and evidence
readers from the initial SQLite cutover. It is not a database installation path,
is not executed by required CI, and must not be used by production services.

The only supported database installation is:

- clean database: `backend/src/main/resources/db/final-schema.sql`;
- observed production database: one separately approved execution of
  `operations/sql/transition-production-to-final.sql`.

Current validation commands are documented in
[`migration/schema/README.md`](../schema/README.md). Historical reports remain
available for audit, but their version labels and checksums are not runtime or
release inputs.
