# Deploy M-Ranked

Owner: application operator. Database bootstrap/restore requires a database
operator. Commands below assume an immutable release at
`/opt/m-ranked/releases/<release>` and symlink `/opt/m-ranked/current`.

## Prerequisites

- Python 3.13+, Node 24 and pnpm;
- PostgreSQL 18 and `psql`;
- system users for API, web, anomaly worker and each collector;
- private systemd credentials under `/etc/m-ranked/credentials`;
- a verified pgBackRest repository and restore drill.

## Build and install

```bash
python3 -m venv .venv
.venv/bin/pip install --requirement requirements.txt --requirement operations/requirements.txt
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
```

Copy the repository tree and the standalone Next.js output into the immutable
release, then atomically update `/opt/m-ranked/current`. Do not copy `.env`,
provider sessions, dumps or credentials into a release.

## Database

A fresh cluster is created by `infra/postgres/init/001-create-roles.sh` and
`002-apply-schema.sh`, which applies `db/migrations/*.sql` in order.
Applications do not migrate a database at startup. Before activating a release:

```sql
SELECT contract_id FROM ops_and_admin.schema_contract;
```

The required value is `live-read-2026-09-13-text-fingerprint`. For an existing cluster, apply
only a separately reviewed forward schema change after a verified backup and
isolated restore; never replay the bootstrap set over a populated database.

## Credentials

Install examples from `operations/env/` as mode 0600 environment files.
Database passwords, `ADMIN_AUTH_USERS` and `ADMIN_CSRF_SECRET` are systemd
credentials loaded by `m-ranked-target-api.service`. Collectors use one
mode-0600 libpq passfile plus one platform-scoped auth file. Session state stays
under `/var/lib/m-ranked/collectors/<platform>`.

## Activate

```bash
systemctl daemon-reload
systemctl enable --now m-ranked-target.target
systemctl enable --now m-ranked-target-maintenance.timer
systemctl enable --now m-ranked-target-backup-daily.timer
systemctl enable --now m-ranked-target-backup-weekly.timer
systemctl enable --now m-ranked-target-backup-monthly.timer
systemctl enable --now m-ranked-target-restore-verify.timer
```

Verify bounded health endpoints, four collector units, anomaly worker, outbox
age, database space, WAL archive and the latest successful restore. A deploy is
not complete while any required unit is restarting or freshness exceeds its
configured threshold.
