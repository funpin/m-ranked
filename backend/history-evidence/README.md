# Ordered reaction history evidence

`ordered-reactions-postgres-v24.json` records a fresh disposable PostgreSQL
installation through V24 and six exercised tests with no skips. Its own database
was removed after the run. The schema hashes identify the exact intermediate
release tested; final migration and HTTP gates must cover the final release.

The test uses exact reaction JSON lexemes from the representative SQLite fixture
`22ec8c52a2e0484bc752221010798d20a66856ff19f4762b09c96749e887b41c`,
post 1: current custom reaction count 8 precedes heart count 4, and the last
stored delta is heart -1 followed by thumbs-up -1. Source deltas must not be
replaced with differences inferred from rendered emoji labels or one API page.

`HistoryReactionDetailsPostgresIntegrationTest` verifies retained order and
deltas, native pagination, exact variation selectors, changed source row hashes,
null versus empty values, strict numeric parsing, and actual restricted-role
access. `DetailPostgresIntegrationTest` exercises existing history, correction,
retention, navigation and public content contracts with the additive fields.

For the mandatory disposable test database, provide
`MRANKED_ADMIN_TEST_POSTGRES_URL`, `MRANKED_ADMIN_TEST_OWNER_USERNAME`,
`MRANKED_ADMIN_TEST_OWNER_PASSWORD`, and `MRANKED_QUERY_TEST_PASSWORD`, then run:

```sh
rtk proxy ./mvnw -Dtest=HistoryReactionDetailsPostgresIntegrationTest,DetailPostgresIntegrationTest test
```

Use Java 21 and the repository's normal Maven configuration. The tests use
transaction rollback for fixtures; their owner requires no superuser permission.
The public API reads only `analytics.publication_history`. Retained source
lexemes and derived evidence stay private. `rawEvidence.reactionDetailsSource`
distinguishes retained legacy deltas, canonical derivation and unavailable
legacy evidence. A null delta is unavailable, while an empty delta is known
to contain no per-reaction changes.
