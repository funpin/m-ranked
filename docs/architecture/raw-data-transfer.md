# Raw data transfer protocol

Дата: 2026-09-16, пересмотрено 2026-09-20 · статус `design draft; not implemented`

> Протокол принят как основа транспорта в [ADR-010](adr/ADR-010-deployment-profiles.md).
> Два уточнения относительно исходного черновика: envelope везёт **канонические**
> батчи, а не сырые payload'ы провайдеров, и тот же envelope применяется
> in-process в однослужебном профиле. Реализуется в фазе P1
> [плана перехода](two-server-migration-plan.md).

## Decision

Server 1 durably stores raw events and a transactional transfer outbox, then pushes
compressed batches over HTTPS/mTLS. Server 2 first durably stores the exact envelope in an
inbox, verifies it, replies ACK, then DataAdapter applies it idempotently to ReadyDB.
Acknowledgement means “durable inbox commit”, not “request received” and not “analysis done”.

## Envelope v1

```json
{
  "schemaVersion": 1,
  "batchId": "uuid-v5-or-content-id",
  "producerId": "server-1/partition",
  "firstCursor": 1001,
  "lastCursor": 1500,
  "createdAt": "UTC RFC3339",
  "recordCount": 500,
  "uncompressedBytes": 123456,
  "compression": "zstd",
  "payloadSha256": "64 lowercase hex",
  "events": "compressed canonical JSONL or protobuf payload"
}
```

Each event has stable `eventId`, platform/account scope, observed/collected timestamps,
source schema version and raw evidence reference. Cursor is a monotonic outbox sequence,
not provider timestamp. Batch limits start at 500 records, 8 MiB compressed, or 30 s age;
tune from p95 bytes/latency. Reject envelopes above hard 16 MiB before allocation.

## State machines

Producer: `pending → sealed → sent → acknowledged → retention-eligible`. Sealing and
outbox cursor allocation happen in the same RawDataDB transaction as raw event persistence.
ACK stores server-2 inbox receipt ID and checksum before producer watermark advances.

Consumer: `received → verified → applying → applied` or `quarantined`. `(producer_id,
batch_id)` and `event_id` are unique. Applying events, recording rejects, and advancing
`applied_cursor` share one ReadyDB transaction. Every input event is accounted as accepted,
duplicate, deferred, or rejected with bounded reason code.

Ordering is guaranteed per producer partition. Cross-platform order is intentionally not
defined. Late events are accepted by event ID/timestamp and produce a new dataset revision;
they never move the transfer watermark backwards.

## Security and bounds

- TLS 1.3; separate client certificate per producer; 30-day overlap rotation; S2 firewall
  accepts ingest only from S1/VPN CIDR.
- Connect/read/write timeouts: 3/30/30 s. Retry exponential 1 s–5 min with full jitter;
  max 20 attempts/hour per batch, then remain pending and alert (never discard).
- SHA-256 verifies compressed payload and per-event semantic hash verifies decoded data.
- Decompression ratio, nesting, string length, count and numeric bounds are enforced before
  database work. Unknown incompatible schema goes to quarantine without advancing apply cursor.
- Raw retention begins only after durable ACK and is at least max(replay window, audit
  retention). Disk high watermark 70% warns, 80% throttles backfill, 90% pauses low-priority
  collection but never deletes unacknowledged data.

## Failure matrix

| Scenario | Deterministic result | Recovery |
|---|---|---|
| Normal | seal, send, durable ACK, apply, advance cursors | automatic |
| S2 down | S1 keeps raw + sealed batches; collectors continue until disk policy | retry with jitter; drain oldest first |
| Unstable network | partial upload has no receipt; same batch ID resent | inbox uniqueness deduplicates |
| ACK lost | producer resends acknowledged batch | S2 returns same receipt/checksum; no second effect |
| S1 restarts | pending/sealed state survives DB restart | resume from acknowledged cursor |
| S2 restarts | received inbox row survives; applying lease expires | new adapter resumes idempotently |
| Both restart | each side resumes from durable state | compare produced/ACK/applied cursors |
| Corrupt batch | checksum mismatch; no ACK; bounded reject metric | resend original; quarantine after repeated mismatch |
| New schema | compatible reader accepts; incompatible batch quarantined | deploy consumer first, then producer |
| S1 disk near full | backfill/low priority stopped; alert | add disk or restore link; never purge unacked |
| Replay/backfill | new replay ID, original event IDs | duplicates accounted, missing range applied |
| ReadyDB restore | restore inbox/apply state, request replay from safe cursor | dedupe converges to same ReadyDB |

## Observability

Per producer expose last produced/ACK/applied cursor, rows/bytes, backlog count/bytes,
oldest age, batch latency, retries, checksum failures, duplicate/reject/quarantine counts and
disk watermarks. Page on cursor regression, unaccounted record count, oldest backlog above
agreed freshness, 90% disk, schema mismatch, or repeated checksum failure.

## Upgrade and replay

Consumer `N+1` must accept producer `N` and `N+1`; deploy consumer first. Producer switches
only after compatibility smoke. Rollback producer while consumer remains backward compatible.
Replay selects cursor range into a separate outbox namespace, never edits historical ACKs.

