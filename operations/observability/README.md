# Operational metrics

The Python exporter produces an atomic Prometheus textfile for a private node
exporter scrape. It performs one read-only query with a five-second statement
timeout for each database connection. It does not scan hot observation rows.
Catalog table/index/partition sizes are aggregate gauges; PostgreSQL insertion
and WAL counters can be converted to daily rates in Prometheus.

Configure environment variables in a protected service credential file:

- `OPS_MONITOR_DATABASE_URL`: the existing `backup` role (`pg_monitor`, replication,
  no superuser/DDL). The exporter only uses its monitoring privileges.
- `OPS_APPLICATION_DATABASE_URL`: the existing `maintenance` role. Sessions use
  `default_transaction_read_only=on`; queries read revision/projection states,
  bounded operational tables, collection summaries and archive/fence state.
- `OPS_REDIS_URL`: private Redis with monitoring-only authentication policy.
- `OPS_DISK_PATH`: the PostgreSQL storage filesystem to measure.
- `OPS_WAL_SPOOL`, `OPS_EVIDENCE_SPOOL`, `OPS_COLD_SPOOL`: absolute provisioned
  directories. Scans skip symlinks and stop at 10,000 entries. Exceeding this
  bound reports an unhealthy source; it cannot silently publish partial sizes.

```sh
rtk proxy .venv/bin/python -m operations.observability.exporter \
  --output /var/lib/node_exporter/textfile_collector/mranked-ops.prom
```

Run once per minute using the service manager on the monitored host. The output
directory must already exist and be writable by the service. Atomic files have
mode `0640`. Source failures discard partial readings, publish `source_up=0`,
and exit with status 1. Only fixed metric names and fixed source/spool enums are
emitted. No SQL text, relation names, account IDs, object URIs, DSNs or exception
details enter the metrics. Missing dependencies are failures, never zero-sized
healthy services.

Coverage includes WAL bytes/archive failures/last archive, streaming lag/standby
count, lock waits, table/index/partition/database size, insert counters,
collection rows per 24 hours and freshness, dataset revision lag, projection
readiness, archive manifests/fences, Redis memory/hits/misses/evictions, spool
bytes/oldest file age and free disk. The 5x/10x gauges are explicit linear
capacity scenarios based on measured current database size. Time-to-full is
derived from observed size growth in Prometheus; the multiplier gauges do not
predict a growth rate.

The application query also reads the bounded SECURITY DEFINER anomaly summary:
candidate/eligible backlog, oldest candidate age, expired leases, retries,
recent failures, independent analysis/source revisions, revision lag and last
successful completion. The worker publishes detector/outcome and
detector/metric/severity counters from packaged bounded enums in its own
`mranked-anomaly.prom` textfile; neither stream uses publication identifiers.

`collector-alerts.yml` and `operations-alerts.yml` contain deployable rule
definitions. Thresholds for spool age and replication reflect the 15-minute
recovery objective and must be accepted against the deployed archive schedule.
The public API Micrometer endpoint is a separate producer. Deploying node
exporter, scrape discovery and alert delivery on production infrastructure is
an external gate; a successful local textfile test does not claim that deployment.
