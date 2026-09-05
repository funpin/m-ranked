# V5 period-activity verification

- Date: 2026-09-03
- PostgreSQL: 18.6
- Migration: `V5__legacy_activity_period_projection.sql`
- SHA-256: `d56c124e2d68eb9897d3fe9d10bde0adf730ea02b84e0d7ec09660775438ea41`
- Disposable verification database: `mranked_period_v5_flyway`

## Result

V5 restores the legacy overview definition of period activity. For each
publication, each metric is the difference between the deterministic first and
last usable observation in `(window_start, window_end]`. Publications released
before the window remain eligible; an old one-point history is not an interval.
A publication released in the window can start at zero only when the applicable
baseline/completeness gate permits it. Missing endpoints remain NULL and a real
negative delta is retained.

The migration renames the V2 publisher to a private implementation and exposes
the original function signature as a `SECURITY DEFINER` wrapper. Runtime roles
cannot call the renamed V2 function, so they cannot publish the obsolete period
calculation. The wrapper inherits V2's newest-revision check, advisory lock and
atomic transaction, then replaces only `institution_period_metrics` and updates
its ready state and returned row count.

All-platform rows never combine platform counters: metric values are NULL and
metric sample size is zero. Coverage means enabled platform count divided by
the four platform enum values. Active institutions with no enabled accounts
remain present at zero coverage.

## Executed evidence

1. A clean Spring Boot start against an empty database made Flyway validate and
   apply exactly V1, V2, V3, V4 and V5, ending at schema version 5.
2. `migration/schema/period-activity-golden.sql` passed on PostgreSQL 18.6 and
   rolled back all fixture writes. It covers:
   - activity on a publication older than the selected window;
   - an observation exactly on the excluded left boundary;
   - synthetic and invalid observations excluded from endpoint selection;
   - an old one-point publication excluded;
   - allowed and denied Telegram publication-time baselines;
   - complete and forced-incomplete non-Telegram baseline gates;
   - NULL metrics and an entirely empty platform remaining NULL;
   - a negative views delta;
   - exact Python-compatible `floor(median + 0.5)` rounding for an even sample;
   - all-platform non-combination, zero metric sample size, platform coverage,
     and an active institution without accounts;
   - runtime privilege isolation and byte-equivalent semantic rows on a second
     rebuild.
3. `migration/schema/smoke.sql` passed, including two rebuilds of one revision,
   all six ready projection states, corrected coverage expectations and denial
   of direct runtime access to the retained V2 function.
4. `./backend/mvnw -f backend/pom.xml -q package` passed the full Java test set.
5. `AdminPostgresIntegrationTest` passed against the real V5 database: 1 test,
   0 failures, 0 errors, 0 skipped. This exercises account enable/disable,
   same-transaction projection publication, audit/outbox writes and rollback
   when rebuild execution is revoked.
6. The running Spring API returned the golden Telegram 1d result:
   `totalReactions=5`, `totalViews=35`, `medianReactions=3`,
   `medianViews=18`, `sampleSize=2`, `coverage=0.400000`.
7. The all-platform API returned every metric value as NULL and
   `sampleSize=0`; the fixture institution had `coverage=0.750000`, and the
   active no-account institution was retained with `coverage=0.000000`.

## Explicit remaining parity gaps

- `institution_period_metrics` and the current overview API DTO do not contain
  previous-window values or trend deltas. V5 therefore does not expose the
  legacy current-versus-previous trend badge.
- The current all-platform DTO has no separate enabled-account count. V5 does
  not overload metric `sampleSize` with that catalog value.
- V5 keeps the pre-existing target policy that platform-specific projection
  dimensions are created for enabled accounts. It only restores the broader
  active-institution dimension for the all-platform coverage view.

These are documented limitations, not silently substituted values.
