# DR standby bootstrap and verification

Owners: database operator executes; security operator approves the private
WireGuard/TLS path and credentials. These commands are a rehearsal recipe, not
authorization to alter production. PostgreSQL must be exactly 18.6 on both
hosts. The secondary is a separate failure domain and is never treated as a
backup.

## Primary prerequisites

Use only the private address in `listen_addresses`. Keep `password_encryption =
'scram-sha-256'`, TLS verification, `wal_level = replica`,
`max_wal_senders = 10`, `max_replication_slots >= 2`, `full_page_writes = on` and
`archive_timeout = '15min'`. The already provisioned `backup` role has only
`LOGIN REPLICATION` plus `pg_monitor`; do not make it owner or superuser.
Allow exactly the DR WireGuard `/32` in `pg_hba.conf`:

```text
hostssl replication backup DR_WIREGUARD_IP/32 scram-sha-256
```

Reload only after `pg_hba_file_rules` has no errors. Firewall PostgreSQL to the
primary/DR private addresses; never publish it on the Internet.

## Initial clone on a production-like DR host

Stop the dedicated standby instance and prove `DR_PGDATA` is its empty,
non-symlink directory. Preserve any prior instance under an incident/change
record; never clear a path merely because a command says it is a PGDATA.
Install a mode-`0600` passfile owned by `postgres`, then run as `postgres`:

```bash
rtk sudo -u postgres env \
  PGPASSFILE=/etc/m-ranked/credentials/standby-replication-pgpass \
  /usr/lib/postgresql/18/bin/pg_basebackup \
  --host=PRIMARY_WIREGUARD_NAME --port=5432 --username=backup \
  --pgdata=DR_PGDATA --format=plain --wal-method=stream \
  --checkpoint=fast --create-slot --slot=mranked_dr --write-recovery-conf \
  --manifest-checksums=SHA256 --progress
rtk sudo -u postgres /usr/lib/postgresql/18/bin/pg_verifybackup DR_PGDATA
```

Before the first start, set `primary_conninfo` to the private hostname with
`sslmode=verify-full`, a pinned CA path and `passfile`; set
`primary_slot_name='mranked_dr'`, `hot_standby=on`, and this archive fallback:

```text
restore_command = 'pgbackrest --config=/etc/m-ranked/pgbackrest.conf --stanza=m-ranked archive-get %f "%p"'
```

The DR repository service needs its write/read repository configurations and
cipher secrets, while the standby PostgreSQL process receives only the
archive-client config. Neither receives an application, collector, Flyway or
admin database credential. Start PostgreSQL only after confirming the generated
`standby.signal` and private listener.

## Acceptance gates

On primary, require one `state='streaming'` row for `application_name='mranked_dr'`,
the expected TLS/WireGuard client address, non-null replay LSN, and replay lag
at most 900 seconds. On DR, require `pg_is_in_recovery() = true` and a read-only
transaction. Also stop streaming on a clone and prove archive recovery advances
from pgBackRest, then restore streaming.

Alert on disconnect, slot WAL growth, replay/archive lag approaching 15 minutes,
timeline divergence, archive spool growth, or disk reaching 70% (85% critical).
Record LSN/timestamps and operator/ticket in the rehearsal evidence consumed by
`cutover-preflight.sh`. Promotion, slot removal, primary endpoint changes and
failover are separate incident-authorized procedures.
