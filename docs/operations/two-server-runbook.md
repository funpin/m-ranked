# Two-server runbook

Дата: 2026-09-16 · commit `b242378` · статус `design draft; not deployed`

## Bring-up

1. Install the same release and schema contracts on both hosts. S1 enables collectors,
   RawDataDB and transfer producer; S2 enables inbox/DataAdapter, ReadyDB, API, SSR, Analyze.
2. Exchange pinned CA/client certificates; S2 firewall admits only S1/VPN to ingest endpoint.
3. Run compatibility probe with an empty and one-record batch; verify repeated batch returns
   same receipt and produces one effect.
4. Run a bounded platform/time-range shadow; compare event ledger and normalized hashes.
5. Canary 10% and observe for 48 h including an intentional test-network interruption in
   staging. Expand only by the gates in migration plan.

## Operator diagnosis

Read four values in order: last produced cursor on S1, last ACK on S1, last received/apply on
S2, oldest backlog age. Produced>ACK means transport/S2 inbox; ACK>applied means DataAdapter or
ReadyDB; cursor equality with stale API means ready/read path. Never reset a cursor to hide lag.

## Link outage

Collectors continue against RawDataDB. Producer retries with jitter. At 70/80/90% disk follow
warn/throttle/pause-low-priority policy. Once link returns, drain incremental data before
replay/backfill and cap DataAdapter so API/SSR reserves remain.

## Upgrade

Deploy consumer N+1, run schema compatibility, then producer N+1. Roll producer back first;
consumer retains N compatibility through the rollback window. See protocol failure matrix and
`rollback-plan.md`.

