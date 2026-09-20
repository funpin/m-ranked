# Collector pipeline and adapter inventory

## Common execution path

```text
systemd m-ranked-target-collector@PLATFORM
  -> python -m collector_target --platform PLATFORM
  -> UTC slot/coalescing + global phase arbiter
  -> Platform adapter registry
  -> provider client
  -> RawCollectionBatch
  -> CanonicalNormalizer
  -> PollCycleCoordinator
  -> one transaction per account batch
  -> PostgreSQL dataset revision/outbox/checkpoints
```

Four systemd instances use the same executable and code.  Process isolation is
intentional: one provider cannot stop the other workers.  Common runtime owns
configuration, scheduling, leases, cancellation, run lifecycle, normalization,
atomic persistence, resume and observability.  Adapters own provider calls and
provider-to-raw conversion; they never create revisions or write SQL.

The phased scheduler keeps a reusable, lazily opened PostgreSQL control
connection for checkpoint and queue work. A separate reusable candidate
session attempts the global advisory lock and becomes the dedicated lease
session only after winning. The winner is read before the lock attempt and
rechecked after it, so a losing worker cannot transiently block the selected
worker. Lease health is the presence of the current backend's exact 64-bit
advisory key in `pg_locks`, not merely a successful `SELECT 1`.

`collector_target.runtime_adapters` and `collector_target.adapters` remain
compatibility import facades for existing tests and callers.  New construction
goes through `collector_target.platforms.registry`; removing the facades is a
separate contract change.

## Provider inventory

| Concern | Telegram | VK | MAX | Rutube |
|---|---|---|---|---|
| Client | Telethon MTProto or public HTTP + optional browser comments | Official VK API client | PyMax user session | Public/official HTTP API |
| Authentication | API ID/hash + session, or public mode | access token in credential env | phone + session DB in credential env | public endpoints |
| Request bound | HTTP 30 s; MTProto cancellation | httpx timeout + token-bucket request rate | `MAX_REQUEST_TIMEOUT_SECONDS`, default 30 s, around connect and every call | bounded httpx requests and request semaphore |
| Account concurrency | 6 default | 3 default, 3 req/s | 1 | 4 accounts, 8 requests |
| Publication identity | stable `m:ID` or `g:GROUP_ID`; album members are identity candidates | stable monitored wall owner/post identity; joint source identity retained | stable message ID | stable video ID |
| Grouping | MTProto/public albums become one logical publication | joint/co-authored post identity | provider repost flag | one video per publication |
| Publication metrics | views, total reactions, comments; shares unavailable | views, likes as reactions, comments, reposts as shares | views, reactions, comments, reposts | views, likes/votes as reactions, comments; shares unavailable |
| Reaction breakdown | preserved, including custom/paid reactions | total only | preserved when supplied | provider total/available engagement |
| Account metric | participants/subscribers, exact public fallback where available | members | participants | public subscriber count when available |
| History completeness | common first-observation age rule, including synthetic public baseline | common rule | common rule | common rule |
| Deletion semantics | exact message/embed lookup; ambiguous/auth/network is transient | exact wall lookup; auth/rate/network is transient | exact message lookup; auth/network is transient | 404/410 missing; 403/rate/network transient |
| Quality details | ambiguous reactions and public comment degradation | transient positive-to-zero suppression and joint-post flags | unsupported values remain `None` with metric quality | unavailable engagement is degraded, not zero |
| Shutdown | disconnect session; close HTTP/browser clients | close HTTP client | close PyMax connection | close HTTP client |

## Canonical field provenance

Every `CanonicalAccountBatch` field is either common context or traceable to a
raw adapter field:

| Canonical area | Source and protection |
|---|---|
| run/platform/partition/version/scheduled time | deterministic `CollectionContext` |
| account observation and identity | provider account/channel response -> `RawAccountObservation` |
| publication ID | deterministic UUID from account ID + stable external ID |
| content group | deterministic UUID from adapter group key |
| identity candidates/public URL | platform adapter identity rules |
| publication/history/repost/quality flags | provider converter raw DTO |
| views/reactions/comments/shares and per-metric quality | raw metrics; `None` is not coerced to zero |
| reaction breakdown | raw reaction mapping; persisted only with its snapshot |
| source evidence/fingerprint | sanitised raw source plus deterministic canonical hashing |
| sampling bucket | UTC logical slot divided by the age-based interval |
| deletion state | adapter probe classification; confirmation derived by repository |
| cursor/refresh cursor | adapter discovery cursor and durable bounded round-robin planner |

Characterization tests in `tests/test_target_collectors.py`, provider client
tests and adapter-contract tests cover representative sanitised objects without
calling live social networks.  PostgreSQL tests cover deterministic replay,
atomic batches, quarantine, revisions and the global phase claim.

An account transaction creates its dataset revision before snapshot inserts
and exposes the id through transaction-local `mranked.dataset_revision_id`.
The publication-latest trigger uses that id and falls back to the latest
revision when an older collector has not set the GUC. Complete revision
metadata and outbox events are written at the end of the same transaction; an
unchanged replay removes its provisional revision before commit.

## Error boundaries

Provider timeout, rate limit, authentication, malformed response and a single
account failure are converted to safe error classes; secrets and exception text
are not persisted.  A validation rejection forces sanitised evidence into
quarantine even when routine raw evidence is disabled.  Database/system errors
before account completion fail the run.  Cancellation cannot leave an account
transaction open.

## Health meanings

- **live**: the systemd process responds or refreshes its phase request.
- **ready**: startup schema contract, credentials and PostgreSQL checks pass.
- **freshness**: completed logical slots and schedule lag remain inside the
  platform-specific operational window.
- **partial**: at least one account batch committed and at least one account
  failed or was rejected.

An unchanged post may create no snapshot before the 24-hour heartbeat.  Snapshot
absence is therefore not a liveness signal; completed runs/account progress and
phase checkpoints are.
