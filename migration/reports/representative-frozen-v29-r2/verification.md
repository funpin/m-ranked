# M-Ranked migration reconciliation

- Report type: `read-only-frozen-verification`
- Generated: `2026-09-06T14:00:57.623926+00:00`
- Gate: **pass**
- Critical mismatches: `0`

## Source

- File: `/private/tmp/mranked-frontend-review-20260905-v3.sqlite`
- SHA-256: `22ec8c52a2e0484bc752221010798d20a66856ff19f4762b09c96749e887b41c`
- SQLite schema: `15`
- Quick check: `ok`
- FK violations: `0`

## Tables

| Table | Rows | Canonical SHA-256 | Min time | Max time |
|---|---:|---|---|---|
| schema_migrations | 15 | `eeb15b6da62a2c2ab43078d7a69df0abc8e1e6587fec24f45a39a19d9e2a5d2a` | 2026-08-01T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| app_state | 2 | `07c2ad57ad7f2fb499d39a0f4a808052230d5e9e8db02926e5412c0f7662c057` | None | None |
| institutions | 207 | `a1a9a8e0639a8f45e20e40f784357212388b9a9a0b11be30c67fb0a5a04a5c55` | 2026-08-01T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| platform_accounts | 824 | `7407467ebb7084c8839f5a52ff6008275088169d6ca664da7964435d81e8cb81` | 2026-08-01T12:00:00+00:00 | 2026-09-05T02:29:13.106098+00:00 |
| channels | 206 | `7f488b025c0d626d0825bb4d4f21d08b87fff7d4b60ee267c7e40ff8b5db0832` | 2026-08-01T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| platform_posts | 618 | `8fe92e1d7b6aab924a26da15dbeacfdabad782f748a1a928409620a60bcbe5e7` | 2026-07-16T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| posts | 206 | `4a943c65abacd8fde8feeb99b9581e0641b6371c55b348a9bd2ac3df06557005` | 2026-07-16T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| post_messages | 208 | `a3f1289d17743a851284c8ee1157b54a66134cf9d9c7e5f4b192869aff87292c` | None | None |
| platform_snapshots | 6768 | `6c12cf731961da348d36591014bc36e33b0e958a8ad9d2c5d7bb6595ce68c879` | 2026-07-16T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |
| reaction_snapshots | 2258 | `eb8e6237fcebf969f475dd05788710d8db84bf11b946ed88a94efb4d6732c9b8` | 2026-07-16T12:00:00+00:00 | 2026-08-01T12:00:00+00:00 |

## Metric/quality totals

- `account_metric_snapshot.rows`: `823`
- `account_metric_snapshot.subscribers`: `8478045`
- `account_metric_snapshot.subscribers_null`: `0`
- `account_metric_snapshot.subscribers_zero`: `4`
- `app_state.rows`: `2`
- `channels.rows`: `206`
- `institutions.rows`: `207`
- `official_rating_observation.rows`: `6`
- `platform_accounts.rows`: `824`
- `platform_posts.additional_authors`: `2`
- `platform_posts.deleted`: `0`
- `platform_posts.distinct_natural_keys`: `618`
- `platform_posts.forced_incomplete`: `0`
- `platform_posts.incomplete`: `1`
- `platform_posts.joint_posts`: `1`
- `platform_posts.reposts`: `1`
- `platform_posts.rows`: `618`
- `platform_snapshots.comments`: `0`
- `platform_snapshots.comments_null`: `2246`
- `platform_snapshots.comments_zero`: `4522`
- `platform_snapshots.max_observed_at`: `2026-08-01T12:00:00+00:00`
- `platform_snapshots.min_observed_at`: `2026-07-16T12:00:00+00:00`
- `platform_snapshots.reactions`: `2023400`
- `platform_snapshots.reactions_null`: `1`
- `platform_snapshots.reactions_zero`: `1`
- `platform_snapshots.rows`: `6768`
- `platform_snapshots.shares`: `0`
- `platform_snapshots.shares_null`: `2256`
- `platform_snapshots.shares_zero`: `4512`
- `platform_snapshots.synthetic`: `0`
- `platform_snapshots.uncertain`: `0`
- `platform_snapshots.views`: `13601975`
- `platform_snapshots.views_null`: `0`
- `platform_snapshots.views_zero`: `1`
- `post_messages.distinct_natural_keys`: `208`
- `post_messages.rows`: `208`
- `posts.album_posts`: `1`
- `posts.albums`: `1`
- `posts.ambiguous_albums`: `1`
- `posts.deleted`: `1`
- `posts.distinct_natural_keys`: `206`
- `posts.forced_incomplete`: `0`
- `posts.incomplete`: `0`
- `posts.reposts`: `1`
- `posts.rows`: `206`
- `reaction_snapshots.breakdown_invalid`: `0`
- `reaction_snapshots.breakdown_rows`: `2259`
- `reaction_snapshots.breakdown_sum`: `674472`
- `reaction_snapshots.breakdown_total_mismatch`: `0`
- `reaction_snapshots.comments`: `3`
- `reaction_snapshots.comments_null`: `748`
- `reaction_snapshots.comments_zero`: `1508`
- `reaction_snapshots.max_observed_at`: `2026-08-01T12:00:00+00:00`
- `reaction_snapshots.min_observed_at`: `2026-07-16T12:00:00+00:00`
- `reaction_snapshots.negative_comment_transitions`: `1`
- `reaction_snapshots.negative_reaction_transitions`: `1`
- `reaction_snapshots.negative_view_transitions`: `1`
- `reaction_snapshots.reactions`: `674472`
- `reaction_snapshots.reactions_null`: `0`
- `reaction_snapshots.reactions_zero`: `1`
- `reaction_snapshots.rows`: `2258`
- `reaction_snapshots.shares_null`: `2258`
- `reaction_snapshots.shares_zero`: `0`
- `reaction_snapshots.synthetic`: `1`
- `reaction_snapshots.uncertain`: `1641`
- `reaction_snapshots.views`: `4533765`
- `reaction_snapshots.views_null`: `0`
- `reaction_snapshots.views_zero`: `1`
- `schema_migrations.rows`: `15`

## Mismatches

None.
