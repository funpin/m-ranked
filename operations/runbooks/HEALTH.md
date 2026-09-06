# Health compatibility and freshness

`GET /api/v1/health/legacy` preserves the legacy `/health` JSON fields and returns 200 with
`status: ok` while operational reads are available. `collector_fresh`, `source_connected`
and platform poll-cycle data report collector state explicitly; stale data does not turn a
liveness response into an unexplained transport failure. A failed operational read returns
only `{"status":"DOWN"}` with 503. Every response is `Cache-Control: no-store`.

`GET /api/v1/health/live` remains process liveness. `/api/v1/health/ready` requires all nine
published projection states at the latest committed revision: six original core states,
`publication_history`, `publication_content` and `legacy_exports`. The revision provider uses
the identical set. `account_latest` updates atomically in that publication transaction and
has no independent projection-state row.

`GET /api/v1/health/freshness` exposes only safe per-platform configured/fresh booleans,
completion times, as-of time, published revision and revision lag. It returns 503 for a
configured collector with absent, stale, failed or future completion, for unpublished raw
revisions, or for unavailable state. An in-progress cycle can retain its previous completed
cycle's freshness. Imported `sqlite-bridge/*` runs never count as live collection success.

V19 provides one SECURITY DEFINER read function with a fixed allowlist and owner-fixed search
path. Public `api_read` loses the old broad SELECT on `operational_checkpoint`. No arbitrary
checkpoint, source evidence, account ID, token, path or raw error text reaches the health
response. Queries use bounded latest-run/checkpoint indexes and a three-second JDBC timeout;
no observation history is scanned.

Set non-secret deployment flags to match the legacy runtime before comparing responses:

- `MRANKED_HEALTH_DATA_SOURCE`: `public_web`, `telegram_web` or `mtproto`.
- `MRANKED_HEALTH_POLL_INTERVAL_MINUTES`: 1–1440; freshness threshold preserves
  `max(poll_interval_minutes * 120, 600)` seconds.
- `MRANKED_INTEGRATIONS_TELEGRAM`, `VK`, `MAX`, `RUTUBE`: configured/missing/unknown.
- `MRANKED_HEALTH_MAX_PHONE_CONFIGURED`, `MRANKED_HEALTH_MAX_SESSION_EXISTS`: booleans;
  health never opens a session or secret file to discover these values.

Legacy checkpoint numeric strings and nulls retain their shape. Older imported
`unparsed_text` timestamp envelopes are understood. Two deliberate safety corrections are
documented: raw Telegram error text is replaced by `upstream_error`, and future completion
times are never treated as fresh. The public API cannot claim a live MTProto connection
without a live connection probe; its legacy-compatible default remains false in that mode.

Run the complete PostgreSQL health test by supplying explicit disposable bootstrap credentials:
`MRANKED_HEALTH_TEST_ADMIN_URL`, `MRANKED_HEALTH_TEST_ADMIN_USERNAME`,
`MRANKED_HEALTH_TEST_ADMIN_PASSWORD` and the restricted `MRANKED_QUERY_TEST_PASSWORD`.
The URL must be loopback and end in `_it`; the test creates and drops its own UUID database.
Optional `MRANKED_HEALTH_TEST_REPORT_PATH` retains a fresh machine report. The mandatory
integration runner provisions these values automatically; no runtime role receives CREATEDB.

```sh
rtk proxy backend/mvnw -f backend/pom.xml -Dtest=LegacyHealthPostgresIntegrationTest test
rtk proxy .venv/bin/python -m operations.http_transition.rehearse \
  --output /private/tmp/mranked-health-http-unique
```

The HTTP producer compares the actual legacy and target JSON after S-final and then keeps
legacy-compatible `/health` responses flowing throughout both directions of cutover. Its
recorded content hash, comparison result and exact Flyway manifest are reproducible evidence.
`operations/nginx/routes/candidate-health.conf` is an inactive candidate adapter for `/health`.
Production route ownership stays on legacy until the release gate and an explicit authorized
route decision. No production network configuration is changed by these tests.
