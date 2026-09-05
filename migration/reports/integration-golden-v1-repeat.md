# M-Ranked migration reconciliation

- Report type: `post-import-reconciliation`
- Generated: `2026-09-03T15:45:22.505217+00:00`
- Gate: **pass**
- Critical mismatches: `0`

## Source

- File: `/private/tmp/mranked-golden-v1.db`
- SHA-256: `b316979027a7f96c4587613f94f149dacfd67444b101eee8b823b09c15e9849d`
- SQLite schema: `15`
- Quick check: `ok`
- FK violations: `0`

## Tables

| Table | Rows | Canonical SHA-256 | Min time | Max time |
|---|---:|---|---|---|
| schema_migrations | 15 | `eeb15b6da62a2c2ab43078d7a69df0abc8e1e6587fec24f45a39a19d9e2a5d2a` | 2026-08-01T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| app_state | 2 | `07c2ad57ad7f2fb499d39a0f4a808052230d5e9e8db02926e5412c0f7662c057` | None | None |
| institutions | 2 | `8ec2d5f0616c5a56a3ab78a5cd5969403b3c35626691a2ff59cd1bd337468434` | 2026-08-01T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| platform_accounts | 4 | `2c1566240a5144f545be6eccd37366c5148221f8a45cead863da9d7cbcd5db09` | 2026-08-01T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| channels | 1 | `f2d53dfc43aa89dbbcdd96bef0da715fabf92a922a9b37a9ae69a4a0e174805d` | 2026-08-01T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| platform_posts | 3 | `4551a900b793599773d2bdcec001949387d1958ee835cd64aa8729202c1b5d88` | 2026-07-29T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| posts | 1 | `d6f764136ac1f8828ecf08ff57eab016445cd06250a31e4f131c03264a7dcce1` | 2026-07-30T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| post_messages | 3 | `914d10ae9eae12e7f47dbfc112d27157d93afcf56203511344f811e6008bc67f` | None | None |
| platform_snapshots | 3 | `b8217005b0dda40b60533c2a6cdbb51627e12707dbc1da0b030b34dc29256dd4` | 2026-07-29T13:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| reaction_snapshots | 3 | `a713316e749e0fadea6d1cd0acdd3153f4ac6737174886609e171f542e39f325` | 2026-07-30T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |

## Metric/quality totals

- `account_metric_snapshot.rows`: `3`
- `account_metric_snapshot.subscribers`: `32345`
- `account_metric_snapshot.subscribers_null`: `0`
- `account_metric_snapshot.subscribers_zero`: `1`
- `app_state.rows`: `2`
- `channels.rows`: `1`
- `institutions.rows`: `2`
- `official_rating_observation.rows`: `6`
- `platform_accounts.rows`: `4`
- `platform_posts.additional_authors`: `2`
- `platform_posts.deleted`: `1`
- `platform_posts.distinct_natural_keys`: `3`
- `platform_posts.forced_incomplete`: `0`
- `platform_posts.incomplete`: `1`
- `platform_posts.joint_posts`: `1`
- `platform_posts.reposts`: `1`
- `platform_posts.rows`: `3`
- `platform_snapshots.comments`: `0`
- `platform_snapshots.comments_null`: `2`
- `platform_snapshots.comments_zero`: `1`
- `platform_snapshots.max_observed_at`: `2026-08-01T07:00:00+00:00`
- `platform_snapshots.min_observed_at`: `2026-07-29T13:00:00+00:00`
- `platform_snapshots.reactions`: `50`
- `platform_snapshots.reactions_null`: `1`
- `platform_snapshots.reactions_zero`: `1`
- `platform_snapshots.rows`: `3`
- `platform_snapshots.shares`: `0`
- `platform_snapshots.shares_null`: `1`
- `platform_snapshots.shares_zero`: `2`
- `platform_snapshots.synthetic`: `0`
- `platform_snapshots.uncertain`: `0`
- `platform_snapshots.views`: `1250`
- `platform_snapshots.views_null`: `0`
- `platform_snapshots.views_zero`: `1`
- `post_messages.distinct_natural_keys`: `3`
- `post_messages.rows`: `3`
- `posts.album_posts`: `1`
- `posts.albums`: `1`
- `posts.ambiguous_albums`: `1`
- `posts.deleted`: `1`
- `posts.distinct_natural_keys`: `1`
- `posts.forced_incomplete`: `0`
- `posts.incomplete`: `0`
- `posts.reposts`: `1`
- `posts.rows`: `1`
- `reaction_snapshots.breakdown_invalid`: `0`
- `reaction_snapshots.breakdown_rows`: `4`
- `reaction_snapshots.breakdown_sum`: `22`
- `reaction_snapshots.breakdown_total_mismatch`: `0`
- `reaction_snapshots.comments`: `3`
- `reaction_snapshots.comments_null`: `0`
- `reaction_snapshots.comments_zero`: `1`
- `reaction_snapshots.max_observed_at`: `2026-07-30T14:00:00+00:00`
- `reaction_snapshots.min_observed_at`: `2026-07-30T12:00:00+00:00`
- `reaction_snapshots.negative_comment_transitions`: `1`
- `reaction_snapshots.negative_reaction_transitions`: `1`
- `reaction_snapshots.negative_view_transitions`: `1`
- `reaction_snapshots.reactions`: `22`
- `reaction_snapshots.reactions_null`: `0`
- `reaction_snapshots.reactions_zero`: `1`
- `reaction_snapshots.rows`: `3`
- `reaction_snapshots.shares_null`: `3`
- `reaction_snapshots.shares_zero`: `0`
- `reaction_snapshots.synthetic`: `1`
- `reaction_snapshots.uncertain`: `0`
- `reaction_snapshots.views`: `190`
- `reaction_snapshots.views_null`: `0`
- `reaction_snapshots.views_zero`: `1`
- `schema_migrations.rows`: `15`

## Import

- `batch_id`: `ae7d403f-1301-5cbf-bd9c-95e1163cb708`
- `source_sha256`: `b316979027a7f96c4587613f94f149dacfd67444b101eee8b823b09c15e9849d`
- `schema_version`: `15`
- `dry_run`: `False`
- `started_at`: `2026-09-03T15:45:22.422664+00:00`
- `finished_at`: `2026-09-03T15:45:22.505254+00:00`
- `rows_read`: `37`
- `rows_written`: `0`
- `rows_by_stream`: `{'app_state': 2, 'channels': 1, 'institutions': 2, 'platform_accounts': 4, 'platform_posts': 3, 'platform_snapshots': 3, 'post_messages': 3, 'posts': 1, 'reaction_snapshots': 3, 'schema_migrations': 15}`
- `projection_rebuild`: `None`
- `warnings`: `[]`

## Mismatches

None.
