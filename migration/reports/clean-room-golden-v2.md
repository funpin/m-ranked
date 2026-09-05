# M-Ranked migration reconciliation

- Report type: `post-import-reconciliation`
- Generated: `2026-09-03T16:15:17.498401+00:00`
- Gate: **pass**
- Critical mismatches: `0`

## Source

- File: `/private/var/folders/rx/pcjkmw2d7tjbjll21rtr8z8h0000gn/T/pytest-of-funpin/pytest-240/test_postgres_bridge_repeat_ca0/golden-v2.db`
- SHA-256: `dca07781b95b76bbeb9cc8826adc700719ad7b55d28bf6ee7c27c3d9e76cc20d`
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
| platform_posts | 3 | `4551a900b793599773d2bdcec001949387d1958ee835cd64aa8729202c1b5d88` | 2026-07-29T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| posts | 1 | `d6f764136ac1f8828ecf08ff57eab016445cd06250a31e4f131c03264a7dcce1` | 2026-07-30T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| post_messages | 3 | `914d10ae9eae12e7f47dbfc112d27157d93afcf56203511344f811e6008bc67f` | None | None |
| platform_snapshots | 4 | `32990564b8348348a219307011e4f5beaa0965fa1cb0b5f80a5126f57f201005` | 2026-07-29T13:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
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
- `platform_posts.distinct_natural_keys`: `3`
- `platform_posts.forced_incomplete`: `0`
- `platform_posts.incomplete`: `1`
- `platform_posts.joint_posts`: `1`
- `platform_posts.reposts`: `1`
- `platform_posts.rows`: `3`
- `platform_snapshots.comments`: `0`
- `platform_snapshots.comments_null`: `3`
- `platform_snapshots.comments_zero`: `1`
- `platform_snapshots.max_observed_at`: `2026-08-01T11:55:00+00:00`
- `platform_snapshots.min_observed_at`: `2026-07-29T13:00:00+00:00`
- `platform_snapshots.reactions`: `51`
- `platform_snapshots.reactions_null`: `1`
- `platform_snapshots.reactions_zero`: `1`
- `platform_snapshots.rows`: `4`
- `platform_snapshots.shares`: `0`
- `platform_snapshots.shares_null`: `1`
- `platform_snapshots.shares_zero`: `3`
- `platform_snapshots.synthetic`: `0`
- `platform_snapshots.uncertain`: `0`
- `platform_snapshots.views`: `1255`
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

- `batch_id`: `06fed09b-b345-5c2e-a1f9-935fba3a583e`
- `source_sha256`: `dca07781b95b76bbeb9cc8826adc700719ad7b55d28bf6ee7c27c3d9e76cc20d`
- `schema_version`: `15`
- `dry_run`: `False`
- `started_at`: `2026-09-03T16:15:17.414965+00:00`
- `finished_at`: `2026-09-03T16:15:17.498450+00:00`
- `rows_read`: `39`
- `rows_written`: `0`
- `rows_by_stream`: `{'app_state': 2, 'channels': 1, 'institutions': 2, 'platform_accounts': 4, 'platform_posts': 3, 'platform_snapshots': 4, 'post_messages': 3, 'posts': 1, 'reaction_snapshots': 4, 'schema_migrations': 15}`
- `projection_rebuild`: `None`
- `warnings`: `[]`

## Mismatches

None.
