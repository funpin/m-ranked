# Platform period baseline

V21 corrects the VK/MAX/Rutube publication-time baseline to match
`app.platform_analytics.platform_activity_cards`. A zero baseline applies when
the publication lies inside the selected window and the first observation inside
that window has age at most `COMPLETE_HISTORY_MAX_FIRST_AGE_MINUTES * 60`.
The original default is six minutes. Publication `history_complete` and the age
of a different lifetime observation do not establish this baseline. With a later
first observation, two window endpoints are required for a delta; a single point
remains unavailable. Telegram keeps its separate explicit baseline rule.

Both the overview and institution-period projections use this rule. Existing
per-metric validity, same-observation endpoints, nulls, rounding and open-left
window boundaries remain part of their calculations.

`analytics.legacy_period_policy` contains append-only policy versions, keyed by
the configuration revision where they take effect. The default is 360 seconds.
For a non-default source configuration, the owner-controlled migration process
must create a new `configuration` dataset revision, insert the policy with that
revision, and rebuild it in one transaction. Inserts for already published or
non-configuration revisions are rejected. A policy lookup for an earlier revision
continues to return that revision's setting.

On an existing installation the policy correction publishes a new revision and rebuilds using the
previously published observation anchor. Thus the correction changes ETags while
the source time window remains comparable. An empty installation stays empty.

`LegacyPeriodOraclePostgresIntegrationTest` tests a clean final-schema installation.
Its oracle executes the original
Python function: 21 scenarios across three platforms, 84 cards and 672 period
metric comparisons. The fixture verifies the reported VK single late snapshot
changes from 1,000 views to unavailable, with a new revision and unchanged anchor.
It also checks policy revision pinning and rejected retroactive writes.

The `period-activity-golden.sql` values stay unchanged; its ACL assertion follows
the final-contract maintenance/recovery-only historical-bootstrap boundary. Its current
Java adapter corrects one obsolete VK expectation that assumed
`history_complete` permitted a one-hour-old single snapshot. The remaining
historical SQL assertions and the fixed-cohort SQL fixture continue to run.
