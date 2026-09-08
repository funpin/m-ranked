# Collector tracked-publication contract v1

This contract governs target-collector refresh and deletion evidence. It is an
internal ingestion contract; it does not add a public HTTP endpoint.

## Selection and fairness

For each enabled account and deterministic collection run:

1. The adapter performs normal discovery first. `DISCOVERY_LIMIT` is never
   shared with refresh.
2. The repository returns at most `COLLECTOR_REFRESH_SCAN_LIMIT` active
   publications newer than `TRACK_POST_FOR_HOURS`, circularly ordered after the
   account's deterministic publication-UUID cursor.
3. Already-discovered and not-yet-due rows advance the scan cursor without
   consuming point-read budget.
4. Due rows consume `COLLECTOR_REFRESH_LIMIT`. When the budget is full, the
   cursor stops at the last selected row so the following row leads the next
   circular scan.
5. `collector.refresh_cursor.v1` is committed in the same account transaction
   as observations. A failed run does not advance it; a deterministic resume
   selects the same page.

Defaults are `100` point reads and `400` scanned rows. The scan limit must be at
least the point-read limit. Provider batch calls are additionally chunked to at
most 100 identifiers.

## Deletion outcomes

`ingest.deletion_observation.outcome` has these meanings:

| Outcome | Counter effect | Permitted evidence |
|---|---:|---|
| `present` | reset to `0` | publication returned by discovery or exact point read |
| `missing` | increment by `1` | successful authoritative point lookup only |
| `confirmed_deleted` | derived at threshold | repository-derived; adapters cannot emit it |
| `transient_error` | unchanged | auth, rate, transport, `5xx`, parser/ambiguous response |
| `unsupported` | unchanged | no safe provider-specific point identity/operation |

The target minimum threshold is two; `DELETION_CONFIRMATION_CHECKS` may raise
it. Confirmation updates only `ingest.publication.deleted_at`. It never deletes
publication identity, snapshots, reactions, lineage, or earlier probe evidence.
A later actual observation records `present`, resets the counter, and clears the
tombstone. Tombstoned rows are no longer point-refreshed; recovery therefore
requires an actual rediscovery, matching legacy behavior.

## Authoritative provider evidence

| Provider/mode | Authoritative missing | Never authoritative |
|---|---|---|
| Telegram MTProto | successful exact `get_messages(ids)` omits all member IDs | recent-page omission, FloodWait/auth/transport failure |
| Telegram public | exact embed `404`/`410`, or recognized Telegram deleted/service marker | feed omission, `401`/`403`, `429`, `5xx`, unrecognized HTTP-200 body |
| VK | successful `wall.getById` omits the requested identity or marks it deleted | `wall.get` omission, VK/HTTP auth, rate, transport, malformed response |
| MAX | successful exact `get_messages` omits the requested message | history omission, session/auth/rate/transport failure |
| RUTUBE | exact `/api/video/{id}/?format=json` returns `404`/`410` | channel-list omission, auth/rate/transport/`5xx`, incomplete/mismatched body |

## Atomicity and idempotence

Normalization rejects adapter-emitted `confirmed_deleted`, duplicate probes for
one publication, malformed reason codes, naive timestamps, and thresholds below
two. Persistence locks and verifies publication ownership, derives the next
counter from durable evidence, inserts one probe per publication/run/instant,
and applies any tombstone/recovery in the same transaction as snapshots,
account result, refresh cursor, dataset revision, and outbox event. Replaying an
identical committed account batch produces no second probe or revision.

The schema required by this contract already exists in V1
(`ingest.deletion_observation`, `ingest.publication.deleted_at`, and
`ops_and_admin.operational_checkpoint`), so this implementation requires no V6
migration.
