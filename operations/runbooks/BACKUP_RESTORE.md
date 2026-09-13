# Backup, WAL and PITR

Owners: database operator and restore operator. Targets are RPO ≤ 15 minutes and
RTO ≤ 2 hours. A streaming standby is not a backup.

Use the example pgBackRest configurations in `operations/backup/`. Keep the
encrypted repository outside the primary failure domain, use separate
archive/backup/restore SSH identities, pin host keys and deny interactive
shells.

PostgreSQL must archive WAL continuously with `archive_timeout=15min`.
Enable daily, weekly and monthly backup timers plus daily restore verification:

```bash
systemctl enable --now m-ranked-target-backup-daily.timer
systemctl enable --now m-ranked-target-backup-weekly.timer
systemctl enable --now m-ranked-target-backup-monthly.timer
systemctl enable --now m-ranked-target-restore-verify.timer
```

The verifier restores into a new private directory, starts PostgreSQL without a
network listener, checks page checksums and `pg_amcheck --all`, requires
PostgreSQL 18.6 and schema contract `live-read-2026-09-13-text-fingerprint`, records the latest
dataset revision and removes only its own temporary cluster. Quarterly
`m-ranked-target-pitr-drill.timer` replays archived WAL to a chosen point.

During an incident, freeze writers, retain the damaged primary, restore to a
new host/path and verify contract, checksums, revision and RPO/RTO before any
promotion. Provider session files and identity receipts live outside PostgreSQL;
back them up separately with distinct encryption and verify their inventory.
