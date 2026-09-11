# Operational metrics

`operations.observability.exporter` writes a bounded Prometheus textfile from:

- PostgreSQL server statistics;
- safe application counters, outbox and anomaly backlog;
- WAL/evidence/cold spool sizes;
- filesystem capacity.

Configure `OPS_MONITOR_DATABASE_URL`, `OPS_APPLICATION_DATABASE_URL`,
`OPS_DISK_PATH` and the three `OPS_*_SPOOL` paths. The exporter emits only
fixed metric names and aggregate numbers; exception text and DSNs are never
included.
