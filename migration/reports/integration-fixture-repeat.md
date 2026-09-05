# M-Ranked migration reconciliation

- Report type: `post-import-reconciliation`
- Generated: `2026-09-03T15:44:51.175411+00:00`
- Gate: **pass**
- Critical mismatches: `0`

## Source

- File: `/private/tmp/mranked-baseline.GzIBxE/legacy.db`
- SHA-256: `d7d52b317864b95cbbe368491c8a27a61fd66d26bdd2e43f89386e073698b1a9`
- SQLite schema: `15`
- Quick check: `ok`
- FK violations: `0`

## Tables

| Table | Rows | Canonical SHA-256 | Min time | Max time |
|---|---:|---|---|---|
| schema_migrations | 15 | `ba4046e55c73221f8811dc35cffe9a380f1b27426031788bebaf463ee8498574` | 2026-08-30T15:41:16.757594+00:00 | 2026-09-03T14:25:18.570081+00:00 |
| app_state | 3 | `d2faa0b7646c31cfef1d32895667157516cb627dd5c7299fb65a6158d0d1291b` | None | None |
| institutions | 2 | `fc2ab97b4853c9172081661aa4693d60e1c5d5d42f1560a882fceba283590b59` | 2026-09-01T18:53:01.640739+00:00 | 2026-09-01T19:04:01.205692+00:00 |
| platform_accounts | 7 | `3231c8cc80b0dfe0b6efa95e6a24213e92c8eaf91ae24b585a679b911d257443` | 2026-09-01T18:53:01.641836+00:00 | 2026-09-01T19:03:54.209115+00:00 |
| channels | 2 | `d8341f10636c3fc01d565365e15f7326ed30079641ed06806e7e440e344da0f5` | 2026-09-01T18:53:01.641799+00:00 | 2026-09-01T19:03:54.205044+00:00 |
| platform_posts | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | None | None |
| posts | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | None | None |
| post_messages | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | None | None |
| platform_snapshots | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | None | None |
| reaction_snapshots | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | None | None |

## Metric/quality totals

- `account_metric_snapshot.rows`: `0`
- `account_metric_snapshot.subscribers`: `None`
- `account_metric_snapshot.subscribers_null`: `0`
- `account_metric_snapshot.subscribers_zero`: `0`
- `app_state.rows`: `3`
- `channels.rows`: `2`
- `institutions.rows`: `2`
- `official_rating_observation.rows`: `12`
- `platform_accounts.rows`: `7`
- `platform_posts.additional_authors`: `None`
- `platform_posts.deleted`: `None`
- `platform_posts.distinct_natural_keys`: `0`
- `platform_posts.forced_incomplete`: `None`
- `platform_posts.incomplete`: `None`
- `platform_posts.joint_posts`: `None`
- `platform_posts.reposts`: `None`
- `platform_posts.rows`: `0`
- `platform_snapshots.comments`: `None`
- `platform_snapshots.comments_null`: `None`
- `platform_snapshots.comments_zero`: `None`
- `platform_snapshots.max_observed_at`: `None`
- `platform_snapshots.min_observed_at`: `None`
- `platform_snapshots.reactions`: `None`
- `platform_snapshots.reactions_null`: `None`
- `platform_snapshots.reactions_zero`: `None`
- `platform_snapshots.rows`: `0`
- `platform_snapshots.shares`: `None`
- `platform_snapshots.shares_null`: `None`
- `platform_snapshots.shares_zero`: `None`
- `platform_snapshots.synthetic`: `0`
- `platform_snapshots.uncertain`: `0`
- `platform_snapshots.views`: `None`
- `platform_snapshots.views_null`: `None`
- `platform_snapshots.views_zero`: `None`
- `post_messages.distinct_natural_keys`: `0`
- `post_messages.rows`: `0`
- `posts.album_posts`: `None`
- `posts.albums`: `0`
- `posts.ambiguous_albums`: `None`
- `posts.deleted`: `None`
- `posts.distinct_natural_keys`: `0`
- `posts.forced_incomplete`: `None`
- `posts.incomplete`: `None`
- `posts.reposts`: `None`
- `posts.rows`: `0`
- `reaction_snapshots.breakdown_invalid`: `0`
- `reaction_snapshots.breakdown_rows`: `0`
- `reaction_snapshots.breakdown_sum`: `0`
- `reaction_snapshots.breakdown_total_mismatch`: `0`
- `reaction_snapshots.comments`: `None`
- `reaction_snapshots.comments_null`: `None`
- `reaction_snapshots.comments_zero`: `None`
- `reaction_snapshots.max_observed_at`: `None`
- `reaction_snapshots.min_observed_at`: `None`
- `reaction_snapshots.negative_comment_transitions`: `None`
- `reaction_snapshots.negative_reaction_transitions`: `None`
- `reaction_snapshots.negative_view_transitions`: `None`
- `reaction_snapshots.reactions`: `None`
- `reaction_snapshots.reactions_null`: `0`
- `reaction_snapshots.reactions_zero`: `None`
- `reaction_snapshots.rows`: `0`
- `reaction_snapshots.shares_null`: `None`
- `reaction_snapshots.shares_zero`: `0`
- `reaction_snapshots.synthetic`: `None`
- `reaction_snapshots.uncertain`: `None`
- `reaction_snapshots.views`: `None`
- `reaction_snapshots.views_null`: `None`
- `reaction_snapshots.views_zero`: `None`
- `schema_migrations.rows`: `15`

## Import

- `batch_id`: `46d83603-8dde-50db-8fee-8384aef87737`
- `source_sha256`: `d7d52b317864b95cbbe368491c8a27a61fd66d26bdd2e43f89386e073698b1a9`
- `schema_version`: `15`
- `dry_run`: `False`
- `started_at`: `2026-09-03T15:44:51.094645+00:00`
- `finished_at`: `2026-09-03T15:44:51.175453+00:00`
- `rows_read`: `29`
- `rows_written`: `0`
- `rows_by_stream`: `{'app_state': 3, 'channels': 2, 'institutions': 2, 'platform_accounts': 7, 'platform_posts': 0, 'platform_snapshots': 0, 'post_messages': 0, 'posts': 0, 'reaction_snapshots': 0, 'schema_migrations': 15}`
- `projection_rebuild`: `None`
- `warnings`: `[]`

## Mismatches

None.
