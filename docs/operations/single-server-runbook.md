# Single-server runbook

Дата: 2026-09-16 · commit `b242378` · статус `draft; current deployment observed read-only`

Use `operations/runbooks/DEPLOY.md` for the existing release procedure. This runbook adds gates
for the target profile.

## Install/update gate

1. Provision 4 vCPU/8 GiB/100 GB NVMe, UTC, firewall 80/443 inbound and provider/backup
   destinations outbound. PostgreSQL listens on loopback only.
2. Use separate service users and DB roles; secrets only in systemd credentials/passfiles.
3. Restore/initialize PostgreSQL 18.6 with checksums, apply reviewed migrations one by one.
4. Start DB, API and SSR; confirm live/ready endpoints. Start collectors one by one with
   offsets. Start Analyze last with batch 5 after resource headroom is visible.
5. Compare schema contract, four collector freshness values, outbox oldest age, Analyze queue,
   disk, backup age and external pages. Update is not complete while any is unknown.

Resource controls follow `deployment-topologies.md`. Dependency ordering uses readiness and
retry, never only systemd `After=`. Analyze failure is degraded operation; ingestion/API stay up.

## Routine checks

- 15 min: collector freshness, outbox/inbox age, API/SSR latency/errors;
- hourly: disk/WAL/temp, DB connections/locks, Analyze backlog/leases;
- daily: backup age and verification result; weekly: capacity trend;
- quarterly: isolated restore/PITR/replay drill with measured RPO/RTO.

## Immediate current-host constraints

Do not enable Analyze backfill or a load test on the observed 1-vCPU host. First repair 0027,
outbox and disk capacity, then establish 24-hour metrics. Any service/config/restart action on
production requires explicit owner approval.

