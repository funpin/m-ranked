# External legacy reference

Alpha ships one interface: `frontend/` (Next.js) with the Spring API.
The Python UI, its templates and its runtime entry points have been removed.
Collectors, SQLite import and reverse-sync data compatibility remain available.

Numeric, CSV and HTTP rollback oracles still require the original implementation.
They load it only from an explicitly configured, trusted external checkout:

```bash
git worktree add --detach /tmp/mranked-legacy-reference 8475074f4a41cd9d8e13b623f1c51adf30426c00
export MRANKED_LEGACY_REFERENCE_ROOT=/tmp/mranked-legacy-reference
```

This is test tooling, not a second deployed interface. Nothing is downloaded,
restored from Git or started automatically by the application or Docker Compose.
Without this environment variable, reference-dependent verification fails with
an explicit error; it cannot report successful parity. The standalone legacy CSV
unit tests explicitly skip when the external reference is absent. CI checks out
the pinned reference separately before running migration gates.

`migration.legacy_reference` imports the reference under an isolated module name
so it cannot replace the current collector modules. Projection reconciliation
records the external app tree SHA-256. Existing evidence reports describe the
earlier release and are not rewritten by this removal.

Production routing and rollback scripts refer to the separately installed legacy
release. Do not use alpha as that rollback artifact; retain the original release
and service configuration on the production host until its migration is approved.
