# M-Ranked migration reconciliation

- Report type: `post-import-reconciliation`
- Generated: `2026-09-03T15:50:51.987752+00:00`
- Gate: **fail**
- Critical mismatches: `1`

## Source

- File: `/private/tmp/mranked-golden-deletion.db`
- SHA-256: `fd29264fb594fddd7e2ee3bca0a72a3b81092b919e5bd10bafd81d7bf286d5a9`
- SQLite schema: `15`
- Quick check: `ok`
- FK violations: `0`

## Tables

| Table | Rows | Canonical SHA-256 | Min time | Max time |
|---|---:|---|---|---|
| schema_migrations | 15 | `eeb15b6da62a2c2ab43078d7a69df0abc8e1e6587fec24f45a39a19d9e2a5d2a` | 2026-08-01T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| app_state | 2 | `8daf6ca8b9814938e25795523e6577ca2581a029c068bee6a64728c80b299f39` | None | None |
| institutions | 2 | `1900b1feed1ce17d253cd9211a847e42e7b5b0b86962790a39466f20aa31b609` | 2026-08-01T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| platform_accounts | 4 | `2c1566240a5144f545be6eccd37366c5148221f8a45cead863da9d7cbcd5db09` | 2026-08-01T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| channels | 1 | `f2d53dfc43aa89dbbcdd96bef0da715fabf92a922a9b37a9ae69a4a0e174805d` | 2026-08-01T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| platform_posts | 2 | `90136fc86c273ab3b1f07e714474c16b0a182bffd6870733b752b18757b02b06` | 2026-07-29T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| posts | 1 | `d6f764136ac1f8828ecf08ff57eab016445cd06250a31e4f131c03264a7dcce1` | 2026-07-30T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| post_messages | 3 | `914d10ae9eae12e7f47dbfc112d27157d93afcf56203511344f811e6008bc67f` | None | None |
| platform_snapshots | 3 | `94b3050bd9ebc00af0ca242b9029b06b85c9de3d7788a6567441787e2409c944` | 2026-07-29T13:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| reaction_snapshots | 4 | `f8fae1f4d098b4193a59ff777c07f923d322e8b1ddeca1661913aa1d6d165029` | 2026-07-30T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |

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
- `platform_posts.distinct_natural_keys`: `2`
- `platform_posts.forced_incomplete`: `0`
- `platform_posts.incomplete`: `1`
- `platform_posts.joint_posts`: `1`
- `platform_posts.reposts`: `1`
- `platform_posts.rows`: `2`
- `platform_snapshots.comments`: `0`
- `platform_snapshots.comments_null`: `2`
- `platform_snapshots.comments_zero`: `1`
- `platform_snapshots.max_observed_at`: `2026-08-01T11:55:00+00:00`
- `platform_snapshots.min_observed_at`: `2026-07-29T13:00:00+00:00`
- `platform_snapshots.reactions`: `51`
- `platform_snapshots.reactions_null`: `1`
- `platform_snapshots.reactions_zero`: `0`
- `platform_snapshots.rows`: `3`
- `platform_snapshots.shares`: `0`
- `platform_snapshots.shares_null`: `0`
- `platform_snapshots.shares_zero`: `3`
- `platform_snapshots.synthetic`: `0`
- `platform_snapshots.uncertain`: `0`
- `platform_snapshots.views`: `1005`
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
- `reaction_snapshots.breakdown_rows`: `6`
- `reaction_snapshots.breakdown_sum`: `37`
- `reaction_snapshots.breakdown_total_mismatch`: `0`
- `reaction_snapshots.comments`: `6`
- `reaction_snapshots.comments_null`: `0`
- `reaction_snapshots.comments_zero`: `1`
- `reaction_snapshots.max_observed_at`: `2026-07-30T15:00:00+00:00`
- `reaction_snapshots.min_observed_at`: `2026-07-30T12:00:00+00:00`
- `reaction_snapshots.negative_comment_transitions`: `1`
- `reaction_snapshots.negative_reaction_transitions`: `1`
- `reaction_snapshots.negative_view_transitions`: `1`
- `reaction_snapshots.reactions`: `37`
- `reaction_snapshots.reactions_null`: `0`
- `reaction_snapshots.reactions_zero`: `1`
- `reaction_snapshots.rows`: `4`
- `reaction_snapshots.shares_null`: `4`
- `reaction_snapshots.shares_zero`: `0`
- `reaction_snapshots.synthetic`: `1`
- `reaction_snapshots.uncertain`: `0`
- `reaction_snapshots.views`: `330`
- `reaction_snapshots.views_null`: `0`
- `reaction_snapshots.views_zero`: `1`
- `schema_migrations.rows`: `15`

## Import

- `batch_id`: `55c54be9-432d-54ff-871c-783395f1fc96`
- `source_sha256`: `fd29264fb594fddd7e2ee3bca0a72a3b81092b919e5bd10bafd81d7bf286d5a9`
- `schema_version`: `15`
- `dry_run`: `False`
- `started_at`: `2026-09-03T15:50:51.406473+00:00`
- `finished_at`: `2026-09-03T15:50:51.989225+00:00`
- `rows_read`: `37`
- `rows_written`: `146`
- `rows_by_stream`: `{'app_state': 2, 'channels': 1, 'institutions': 2, 'platform_accounts': 4, 'platform_posts': 2, 'platform_snapshots': 3, 'post_messages': 3, 'posts': 1, 'reaction_snapshots': 4, 'schema_migrations': 15}`
- `projection_rebuild`: `{'comparison': 5224, 'publication_hourly': 2535, 'publication_latest': 4, 'dataset_revision_id': 112, 'institution_daily_metrics': 64, 'institution_period_metrics': 480, 'institution_monthly_metrics': 56}`
- `warnings`: `[]`

## Mismatches

- `{"actual": 2, "check": "source_rows_missing_since_prior_batch", "critical": true, "details": {"policy": "never delete automatically; operator must explain hard delete"}, "expected": 0, "scope": "all", "status": "fail"}`
