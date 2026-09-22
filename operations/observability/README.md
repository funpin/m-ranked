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

## Security counters

The API writes `m-ranked-api-security.prom` into the node_exporter textfile
directory: one counter, `mranked_api_security_events_total`, labelled by event
(`auth.success`, `auth.failure`, `auth.throttled`, `authz.denied`,
`csrf.rejected`, `session.opened`, `session.closed`, `session.revoked`) and by a fixed reason enum. Set
`MRANKED_SECURITY_METRICS_FILE` to enable it; `security-alerts.yml` holds the
matching rules. The counters carry no account name. The structured `security_event`
journal lines identify an account by a truncated SHA-256 fingerprint, which
correlates events without printing the login; the password, the one-time code
and the CSRF token never appear in either place.
