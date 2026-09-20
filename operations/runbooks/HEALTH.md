# Health and freshness

- `GET /api/v1/health/live` proves process liveness.
- `GET /api/v1/health/ready` proves the database and schema contract are
  available.
- `GET /api/v1/health/freshness` reports bounded per-platform collection
  freshness and the current live dataset revision.
- `GET /api/v1/health/legacy` preserves the frozen compatibility response.

Collector process liveness and data freshness are intentionally separate:

- `live`: the unit is active and either completes work or refreshes a
  `collector.phase.v1` requested/active checkpoint;
- `ready`: PostgreSQL and the schema contract passed startup checks;
- `freshness`: completed platform runs and phase schedule lag fit the agreed
  platform window;
- `partial`: successful account batches were committed but at least one account
  failed or was quarantined.

A worker may wait behind another healthy phase and create no run. Conversely,
an active process with increasing schedule lag is live but not fresh. The
watchdog uses run/account progress plus phase state; it never uses publication
snapshot timestamps because unchanged metrics are intentionally deduplicated.

Troubleshooting phased workers:

- confirm the startup log has `schedule_mode`, `platform`, `partition` and
  `collector_version`; confirm `mranked_collector_schedule_mode_info` agrees;
- repeated `phase=waiting`: inspect the active platform and phase wait metric;
- lease appears stuck: verify the holder database session; terminating a dead
  session releases the advisory lock automatically. A live lease probe must
  find the exact key under the current `pg_backend_pid()` in `pg_locks`;
- lag grows: compare total cycle time with the capacity table in ADR-009;
- `GlobalPhaseLeaseLost`: investigate PostgreSQL connectivity; the cycle is
  cancelled to avoid unprotected overlap;
- `partial`: inspect safe per-account error codes and quarantine evidence;
- old `running` run: restart the same platform/version/partition to resume its
  deterministic `scheduled_at`.

Transfer health is per `producer`:

- `mranked_transfer_last_produced_cursor`, `last_acknowledged_cursor` and
  `last_applied_cursor` must be monotonic;
- `backlog_rows`, `backlog_bytes` and `oldest_backlog_age_seconds` describe only
  unacknowledged work; the warning SLO is 30 minutes;
- `outbox_rows`/`outbox_bytes`, `batch_latency_seconds`, `retries_total`,
  `checksum_failures_total`, `duplicates_total`, `rejects_total`,
  `quarantines_total` and `unaccounted_records` localise delivery failures;
- disk watermarks are 70% warn, 80% stop backfill and 90% pause low-priority
  collection. Never delete an unacknowledged row.

Transfer troubleshooting:

- growing backlog: compare produced/ACK cursors, inspect `last_error_code`, restore
  the consumer/link, and drain oldest cursor first;
- checksum error: compare stored `payload_sha256` with the exact compressed bytes and
  resend the original row; repeated failures page;
- incompatible schema quarantine: deploy a backward-compatible consumer first, then
  explicitly replay the batch; quarantine never advances apply cursor;
- stuck apply cursor: inspect `transfer_inbox.state`; a resent
  `(producer_id,batch_id)` returns the same receipt and resumes idempotently. Compare
  the four accounting counters with `record_count` before intervention;
- retention: purge only `state='acknowledged'` older than the audit/replay window.
  `sealed` and `sent` are never retention-eligible, including under disk pressure.

All health responses are `no-store`. Readiness does not wait for a projection
publisher: public data is read directly from canonical tables. A configured
collector with no successful recent run makes freshness unhealthy, while an
in-progress run may retain the previous completed run's timestamp.

Verify after deploy:

```bash
curl --fail http://127.0.0.1:8080/api/v1/health/live
curl --fail http://127.0.0.1:8080/api/v1/health/ready
curl --fail http://127.0.0.1:8080/api/v1/health/freshness
```
