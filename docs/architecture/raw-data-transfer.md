# Raw data transfer protocol

Дата: 2026-09-16, реализовано 2026-09-21 · статус `P1 и P2.1 implemented`

> Протокол принят как основа транспорта в [ADR-010](adr/ADR-010-deployment-profiles.md).
> Два уточнения относительно исходного черновика: envelope везёт **канонические**
> батчи, а не сырые payload'ы провайдеров, и тот же envelope применяется
> in-process в однослужебном профиле. Профиль A реализован в фазе P1
> [плана перехода](two-server-migration-plan.md).

## Что реализовано

| Часть протокола | Состояние |
|---|---|
| envelope v1, детерминированный `batchId`, границы, карантин | реализовано (P1) |
| transfer outbox/inbox, идемпотентное применение | реализовано (P1) |
| транспорт in-process | реализовано (P1) |
| приёмник `transfer_ingest`, HTTPS + mTLS, привязка `producer_id` к сертификату | реализовано (P2.1) |
| экспоненциальный backoff с полным jitter, окно 20 попыток в час | реализовано (P2.1) |
| ретенция после ACK, метрики и алерты обеих сторон | реализовано |
| пороги диска 70/80/90 %, приостановка низкоприоритетного сбора | не реализовано, P2.2 |
| replay в отдельное пространство имён outbox | не реализовано, P4 |

## Decision

Server 1 durably stores canonical events and a transactional transfer outbox, then pushes
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
  "events": "zstd-compressed canonical JSONL payload"
}
```

Each event has stable `eventId`, platform/account scope, observed/collected timestamps,
source schema version and raw evidence reference. Cursor is a monotonic outbox sequence,
not provider timestamp. Batch limits start at 500 records, 8 MiB compressed, or 30 s age;
tune from p95 bytes/latency. Reject envelopes above hard 16 MiB before allocation.

P1 seals one `CanonicalAccountBatch` as one JSONL event. The reader accepts up to
500 events so later aggregation does not change the envelope contract. `batchId` is
UUIDv5 over the SHA-256 of the canonical compressed payload; retrying the same batch
therefore produces the same ID. `eventId` is UUIDv5 over platform, account and the
semantic hash of the canonical batch. Sanitisation happens before canonical JSON.

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

`ops_and_admin.transfer_outbox` stores the payload itself and therefore is not the
existing `outbox_event`: the latter is a small cache/domain notification tied to a
non-null dataset revision and cannot support replay after Server 1 history is trimmed.
`transfer_inbox` durably commits the exact compatible payload and receipt before ACK.
An incompatible version stores only bounded metadata/checksum in quarantine because an
unknown payload cannot be proven secret-free. Profile A
then applies through `PostgresCollectorRepository.persist_account_batch_in_transaction`;
the inbox accounting and applied cursor commit in the same transaction. Direct
collector persistence remains enabled in P1, so local application is deliberately a
duplicate no-op and discards its provisional dataset revision.

## Security and bounds

- TLS 1.3; separate client certificate per producer; 30-day overlap rotation; S2 firewall
  accepts ingest only from S1/VPN CIDR.
- Connect/read/write timeouts: 3/30/30 s on both sides. Retry exponential 1 s–5 min with
  full jitter; max 20 attempts/hour per batch, then remain pending and alert (never
  discard). Exhausting the window never sets `terminal`: that state means an unrecoverable
  batch, not an unreachable peer.
- The receiver refuses a connection carrying no client certificate before reading a byte.
  `CERT_REQUIRED` alone is not sufficient: TLS 1.3 sends client authentication after the
  server's Finished, so an unauthenticated client can otherwise reach the application.
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

## P1 implementation boundary

Implemented: canonical JSONL/zstd envelope, deterministic IDs, hard pre-DB bounds,
transactional outbox sealing, durable inbox/receipt, checksum and semantic hash checks,
idempotent application through the one repository path, oldest-first retry, ACK
deduplication, ACK-only retention, Profile A in-process transport, metrics and alerts.

The HTTPS+mTLS sender validates its HTTPS endpoint, requires client certificate/key/CA,
uses TLS verification and 3/30/30 second bounds. P2 still owns the HTTP receiver,
certificate provisioning/rotation, firewall rules, full-jitter retry scheduler and the
switch to a second host. P1 does not trim Server 1 history or remove direct persistence.
