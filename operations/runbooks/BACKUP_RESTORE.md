# Backup, continuous WAL and PITR

Owners: database operator for primary/standby and restore operator for the DR
host. Targets are RPO no more than 15 minutes and RTO no more than 2 hours.
A streaming standby is not a backup; all three encrypted repositories are
outside the primary failure domain.

## Configure and prove continuous WAL

Install the exact same pinned pgBackRest version on primary, standby,
repository and verifier. Copy
`operations/backup/pgbackrest-primary.conf.example` to both PostgreSQL hosts as
`/etc/m-ranked/pgbackrest.conf`, replace hostnames, set owner `root:postgres`
and mode `0640`, and configure forced-command SSH over the private WireGuard
path. This config contains no repository cipher secret: PostgreSQL hosts can
push WAL but cannot read or delete a repository.

On the DR repository host, install
`pgbackrest-repository.conf.example` as
`/etc/m-ranked/credentials/pgbackrest-repository.conf`, owner
`root:m-ranked-backup-readers`, mode `0640`. It is the authoritative
backup/expire config and holds all three cipher secrets. Backups are initiated
there as `m-ranked-backup`; pgBackRest deliberately rejects `backup` on a
database host configured with remote repositories. The config contacts primary
and standby through forced-command `postgres` SSH identities and, with
`backup-standby=y`, copies pages from standby while primary only coordinates
backup start/stop.

Every exchanged SSH public key must use the pgBackRest forced-command form
documented upstream, with `no-agent-forwarding`, `no-X11-forwarding` and
`no-port-forwarding`; pin host keys with strict checking. A successful
interactive shell is a failed security gate. Give the repository writer and
repository reader different keys and Unix accounts.

Install `pgbackrest-repository-read.conf.example` on the same host as
`/etc/m-ranked/credentials/pgbackrest-repository-read.conf`, owner
`root:m-ranked-backup-readers`, mode `0640`. The forced-command
`m-ranked-backup-read` account receives group-read but no write permission on
repository paths; the verifier uses only that identity. Keep SSH keys distinct
for archive, backup control and restore reads. The three repositories retain 14
daily, 8 weekly and 12 monthly full restore points. At least one repository must
add storage-level immutable/offline protection.

On each PostgreSQL host, create `/var/spool/m-ranked/pgbackrest` mode `0700`,
owner `postgres:postgres`. On the DR repository host create the same spool plus
`/var/lib/m-ranked/backup-reports` as owner
`m-ranked-backup:m-ranked-backup-readers`, mode `0700`, and create
`/srv/m-ranked/pgbackrest/{daily,weekly,monthly}` as owner
`m-ranked-backup:m-ranked-backup-readers`, mode `0750`. The repository config
forces neutral pgBackRest modes (`0750` directories, `0640` files), so the
read-only account can restore but cannot modify backup data. On the isolated
verifier, create `/var/lib/m-ranked/restore-verify` and
`/var/lib/m-ranked/restore-reports` as mode `0700`, owner
`m-ranked-restore:m-ranked-restore`. Install
`operations/backup/pgbackrest-restore.conf.example` as the verifier's
`pgbackrest-restore.conf`, replace its repository secrets and keep it mode
`0600`. Never reuse a production PGDATA path in that file.

PostgreSQL 18 configuration on primary:

```text
archive_mode = on
archive_timeout = '15min'
archive_command = '/opt/m-ranked/current/operations/scripts/wal-archive.sh "%p" "%f"'
full_page_writes = on
max_wal_senders = 10
wal_level = replica
```

With `archive-async=y`, `wal-archive.sh` asks pgBackRest to archive into all
three repositories. pgBackRest can acknowledge PostgreSQL after at least one
repository stores the segment and catches up the others asynchronously; only a
failure of every repository retains the segment in `pg_wal`. Therefore monitor
each repository's archive max/lag independently and require at least one healthy
off-primary line for the 15-minute RPO. Run `stanza-create` on the repository
host and `check` from the repository and both PostgreSQL hosts for repositories
1, 2 and 3 on a clone before reloading PostgreSQL. A reload,
standby configuration or production `archive_command` change requires separate
database-operator approval.

Monitor `pg_stat_archiver`, pgBackRest spool bytes, `pg_wal` bytes, repository
free space and standby replay lag. Alert before 15 minutes, at 70% disk and on
the first archive failure; critical disk threshold is 85%. A cutover gate uses
the stricter `<70%` threshold.

## Base-backup schedule

Enable on the DR repository host only after a successful clone rehearsal:

```bash
rtk sudo systemctl enable --now \
  m-ranked-target-backup-daily.timer \
  m-ranked-target-backup-weekly.timer \
  m-ranked-target-backup-monthly.timer
```

All three schedules create full pgBackRest backups in their dedicated encrypted
repository. pgBackRest expiration enforces the repository counts. Every service
writes a checksummed JSON report; a file existing without a successful restore
does not satisfy the backup gate.

## Daily isolated restore verification

The restore unit belongs on the DR verifier, not the primary. It restores into
`RESTORE_WORK_ROOT/verify.*`, which must be a dedicated filesystem path and can
never be the production PGDATA. The restored PostgreSQL listens on no network
interface; its `trust` rule applies only to a mode-0700 temporary Unix socket.

The script verifies page checksums, starts recovery, requires exact PostgreSQL
18.6, requires the exact successful Flyway V1-V8 scripts and checksums, promotion
out of recovery and all six core projections ready at the latest dataset revision, records the last
replayed WAL LSN/transaction time, runs `pg_amcheck --all`, stops the ephemeral
server, records elapsed seconds and removes only its own temporary directory.
Enable daily verification after a manual successful run:

```bash
rtk sudo systemctl enable --now m-ranked-target-restore-verify.timer
```

The JSON report must have `status=pass`, `rtoMet=true`, all check flags true,
and the ordered V1-V8 version/script/Flyway-checksum manifest. Only after
rechecking its SHA-256, the script atomically publishes successful daily
evidence as `latest.json`; a failed run never replaces it. Successful quarterly
evidence is published separately as `latest-pitr.json`.

## Quarterly PITR drill

The quarterly timer restores repository 1 to 30 minutes before drill execution,
forcing archived-WAL replay rather than only a base-backup start:

```bash
rtk sudo systemctl enable --now m-ranked-target-pitr-drill.timer
rtk sudo systemctl start m-ranked-target-pitr-drill.service
rtk sudo journalctl -u m-ranked-target-pitr-drill.service --since today
```

Record chosen target time, selected backup, last replayed WAL, database/revision
checks, start/finish times, actual RPO and actual RTO. The drill fails if recovery
cannot reach the requested point or exceeds 7200 seconds. Operator and reviewer
sign the report; the timer alone is not evidence of success.

## Incident restore

1. Incident commander records the desired recovery point and freezes writers.
2. Database operator preserves failed primary evidence and restores to a new
   host/path; never use `--delta` against the damaged production PGDATA.
3. Run the same checksum, projection and `pg_amcheck` gates as the verifier.
4. Compare committed revision and timestamps with the incident recovery point.
5. Only explicit incident authorization may promote the restored host or change
   HAProxy/DNS. Application rollback is described separately.

Cold Parquet archives, platform sessions and SQLite S-final are separate assets.
Session backups use a different encryption key and are never placed in the
analytics archive.
