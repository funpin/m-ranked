# Независимая сверка V29 / R30

Машинный оригинал: [verification.json](representative-frozen-v29-r2/verification.json).

| Представление | Строки / distinct keys | SHA-256 source = actual target |
|---|---:|---|
| institutions | 207 / 207 | `e4eea2e2059c2d05161add8d51785bcb1bc1324d0b9dfcb1944396a79331d101` |
| accounts | 824 / 824 | `f90fa98ab14f1e1b766416c579befcd1e4f811491a445ff5f9dbad5b53e89121` |
| subscribers | 823 / 823 | `5b3593fbea25792614d3a6ae98c977ed99623a312a26a1c5311a76c917010b18` |
| publications | 824 / 824 | `45652af02885059738ab8bd06e6af60607c8de27e617328cd818910823fd923d` |
| publication_identities | 827 / 827 | `933c5c796b814beeea563c29d4f3c0112820f4438b965ee1a228efb7b66d54b2` |
| observations | 9026 / 9026 | `45bda43fd9e6c3a3199235544c150fffea5523487a880d49819707b5a87a49b9` |
| reaction_keys | 2259 / 2259 | `d742b3feaeae6bbc6a990168fb8145cb27df88b07d0bc1131eb660e8e1150361` |
| official_rating_values | 6 / 6 | `0fe3f993e2efafcf98e8c5e055bf9b48bb4640f1a008433e8212988fdd1e95dc` |
| ordered_metric_series | 3296 / 3296 | `c61e68f89c733dda3b5b771c32e11c0837935fa12807933ed59922761ce5bd53` |
| operational_checkpoint_text | 1 / 1 | `a7b106b9d35621b83c75303766ef136ee59ce81a3998150ec011a4831b470113` |
| current_account_presentation | 824 / 824 | `02decb56e97e5833bb683e8377d44eca9abdefa49cfd5aecfc667b1d9d92cbc6` |
| projection.fixedCohort | 1611604 / 1611604 | `d3af74a9d0ac0f65d5b116c0a49e36512c5b9872933a2fd087d6834e9eadd7e9` |
| projection.overview | 3308 / 3308 | `5ebd739e82b97dca19359193588e02dc983ac93cc31f737046427672dd09979f` |
| projection.periodMetrics | 19776 / 19776 | `071f9c4923eb9917fc7c17ddff033573191b7c3127a27aa2be336e1348659669` |
| identity_history.presentation | 824 / 824 | `87224a5198133238d5008878322bb9b65c3c603dd56127f45a0d52c832eb64bb` |
| identity_history.native | 4 / 4 | `a7626919d49005084df982db8a44a33560a6d1e776359874825590edc283a69b` |

Все representations имеют 0 duplicate keys. Critical mismatches: 0.

## NULL, zero и временные границы

| Source family / metric | Сумма | NULL | Измеренный 0 |
|---|---:|---:|---:|
| platform_snapshots.views | 13601975 | 0 | 1 |
| platform_snapshots.reactions | 2023400 | 1 | 1 |
| platform_snapshots.comments | 0 | 2246 | 4522 |
| platform_snapshots.shares | 0 | 2256 | 4512 |
| reaction_snapshots.views | 4533765 | 0 | 1 |
| reaction_snapshots.reactions | 674472 | 0 | 1 |
| reaction_snapshots.comments | 3 | 748 | 1508 |
| reaction_snapshots.shares | NULL / unsupported | 2258 | 0 |

Для обеих snapshot families observed_at: `2026-07-16T12:00:00+00:00` → `2026-08-01T12:00:00+00:00`.
Telegram: по одному отрицательному переходу views/reactions/comments; 1 synthetic, 1 641 uncertain; 1 deleted post; 1 album/ambiguous album и 208 member identities.
Platform posts: 1 incomplete, 1 joint post с 2 additional authors, 1 repost. Реакции: 2 259 breakdown rows, total mismatch 0.
Subscribers: 823 facts, сумма 8 478 045, NULL 0, измеренный zero 4. Official M-Rating: 6 values.

NULL не округляется в 0. Canonical timestamps — UTC; exact decimal counters; engagement в projection oracle округляется до 8 знаков. Полные field orders, сериализация и проверки source сохранены в JSON.

Текущий snapshot не содержит target-side command receipts: они проверяются отдельным actual Java/collector → reverse → second S_final rehearsal, а не выдумываются из этой read-only базы.
