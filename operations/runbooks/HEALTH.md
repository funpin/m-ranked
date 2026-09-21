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
- `attempt_window_exhausted_rows` counts batches that used their whole hourly
  attempt budget without an ACK. The batch is safe and still pending; what needs
  a human is the reason the consumer has been unreachable for a full window;
- disk watermarks are 70% warn, 80% stop backfill and 90% pause low-priority
  collection. Never delete an unacknowledged row.

Working set (profile B only):

- `mranked_collector_working_set_released_months_total` counts observation months
  released after Server 2 acknowledged them;
- `mranked_collector_working_set_deferred_months` counts months that are out of
  the tracking window but still held. A steady non-zero value means delivery is
  behind, not that retention is broken: the data is safe, the link is not;
- `mranked_collector_working_set_oldest_retained_unixtime` is the oldest month
  still on this host;
- `mranked_collector_disk_used_percent` drives the 70/80/90 watermarks.

On the receiving side (`transfer_ingest`, profile B only):

- `mranked_transfer_ingest_accepted_total`, `duplicates_total` and
  `rejects_total{reason=...}` account for every request;
- `apply_seconds` and `last_accepted_unixtime` show whether applying keeps up;
- any `rejects_total{reason="client_certificate_required"}` or
  `{reason="producer_identity_mismatch"}` pages: both mean something reached the
  ingest port that should not have.

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
  `sealed` and `sent` are never retention-eligible, including under disk pressure;
- exhausted attempt window: delivery pauses for the remainder of the hour by
  design. Confirm the batch still holds its payload and is not `terminal`, fix the
  link, then clear `available_at` to resume immediately instead of waiting;
- client authentication refused: compare the client certificate common name with
  the producer id the collector is configured to send. A certificate identifies a
  host, and a producer id is `<host>/<partition>`, so only an exact match or a
  whole leading segment authorises the write;
- certificate rotation: issue the new certificate from the same CA and deploy it
  while the old one is still valid. Both are accepted during the overlap, so the
  window needs no coordinated restart;
- retention releases nothing: compare `deferred_months` with the outbox. A month
  is held whenever any batch created at or after its newest row is still
  unacknowledged. Restore delivery first; retention then catches up on its own.
  Retention is also refused outright unless the profile is `b`;
- disk watermark reached: 70% warns, 80% stops backfill, 90% pauses
  low-priority collection. **No watermark authorises deleting unacknowledged
  rows.** At 90% with a full outbox the correct action is to stop and page a
  human, or add disk — never to buy space with the only copy of a measurement;
- observations are append-only. Retention drops whole monthly partitions and
  never issues a `DELETE`: `ingest.observation_immutable` refuses one with
  `ERRCODE 55000`. A publication inside the tracking window therefore keeps all
  of its history, which is what `metric_ever_positive` needs.

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
