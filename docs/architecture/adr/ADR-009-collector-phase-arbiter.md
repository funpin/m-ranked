# ADR-009: isolated collector workers with a PostgreSQL phase arbiter

Status: accepted, feature-flagged rollout.

## Context

Telegram, VK, MAX and Rutube already use one CLI, coordinator, canonical
normalizer and PostgreSQL repository, but their process loops were protected
only by deterministic offsets.  An overrun therefore allowed two heavy cycles
to overlap on the 1 vCPU production host.

The existing production corrections remain invariants: platform-specific
intervals, a 30 second PyMax timeout, set-based persistence, durable run resume,
platform watchdog thresholds and forced quarantine evidence.

## Options considered

1. One process runs all adapters sequentially.  This gives simple exclusion,
   but a blocked provider client, memory leak or process crash stops every
   platform and destroys the existing fault isolation.
2. Four isolated processes share one runtime and one PostgreSQL-backed phase
   arbiter.  A provider failure stays local while a connection-scoped advisory
   lock excludes overlap.  Durable request checkpoints provide ordering and
   observable waiting without holding an account transaction.
3. Four processes use only systemd timers or static offsets.  This is simple,
   but an overrun crosses the next offset and there is no exclusion guarantee.

## Decision

Use option 2.  `python -m collector_target --platform PLATFORM` remains the
only executable.  The adapter registry is exhaustive over `Platform`; the
normalizer and repository remain provider-neutral.

In `phased` mode a worker announces one pending logical slot in
`ops_and_admin.operational_checkpoint` and competes for the global
`collector:global-phase:v1` advisory lock.  The lock has a dedicated autocommit
connection and spans `claim -> collect -> normalize -> persist -> finalize`.
It is automatically dropped when the process or database session dies.  The
existing per-platform/partition lease remains inside the coordinator.

Requests are ordered by the oldest unserved due time and then a stable platform
order.  The selected run keeps the latest UTC-anchored logical `scheduled_at`,
so missed slots coalesce into one run rather than a catch-up storm.  A timed-out
wait retains the same pending request; it does not move its due time forward and
cannot starve behind newly arriving work.

No migration is required: the existing operational checkpoint table and grants
already provide the minimal durable scheduler state.  Network collection never
holds a SQL transaction open.

## Capacity gate

Measured/audited cycle durations are:

| Platform | p50 | p95 / conservative |
|---|---:|---:|
| Telegram | 93 s | 606 s |
| VK | 134 s | 173 s |
| MAX | 93 s | 178 s |
| Rutube | 10–13 min | 13 min |

The three desired five-minute cycles require 320 seconds at p50 before any
safety margin, already more than the 300-second window.  Amortising a 13-minute
Rutube cycle over its one-hour period adds about 65 seconds per five-minute
window.  Strict exclusion and a guaranteed `300/300/300/3600` cadence are
therefore physically incompatible on this host.

Production interval defaults are deliberately unchanged.  They are desired
cadence; schedule lag, overruns and coalesced slots expose the capacity debt.
Possible later operator choices are:

| Policy | Capacity interpretation |
|---|---|
| 5/5/5/60 min | Lowest latency, best effort; lag and coalescing expected. |
| 15/15/15/60 min | p50-safe with margin; not p95-safe. |
| 30/30/30/60 min | Conservative p95 total plus 25% margin fits 30 minutes. |

Changing these production defaults requires a separate operator decision.

## Failure and restart semantics

- A process crash drops both session leases.  A `running` collection run keeps
  its deterministic `scheduled_at` and is resumed before a new slot.
- A completed partial/failed run is terminal and does not pin future slots.
- Loss of the global lease is detected by a bounded probe and cancels the cycle.
- SIGINT/SIGTERM permits a bounded graceful finish, then cancels the cycle.
- A platform cycle deadline prevents an adapter from holding the phase forever.
- One account failure rolls back that account only; successful account batches
  remain committed and the run becomes `partial`.

## Rollout and rollback

`COLLECTOR_SCHEDULE_MODE` is the expand/contract flag:

- `shadow`: calculate/log slots and lag without provider calls;
- `phased`: enable durable requests and global exclusion;
- `legacy`: use the previous offset-only loop and is the immediate rollback.

Canary one platform, then enable all four, observe at least one complete Rutube
period, and inspect lag/overrun/coalescing metrics.  Rollback is an environment
change to `legacy` plus an ordinary unit restart; no schema rollback is needed.
Removing legacy mode is a separate change.
