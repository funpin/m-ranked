# Migration traceability matrix

Review state, 2026-09-06: additive Flyway **V1–V29**, with V1–V8 byte-identical to
`a7a2f09ff156eb72445f04f40dbe0e93d3378911`. **Writer Gate W is CLOSED. All production
routes and writers remain authoritative on legacy.** Local PASS does not grant a
route switch, writer transition, partition deletion or removal of legacy runtime.
This matrix supersedes interim V8/V15/V20 findings; their original reports remain.
The [legacy contract matrix](baseline/legacy-contract-matrix.md) is authoritative.

## Evidence

- **I**: [mandatory integration r17](reports/integration-review-20260906-r17/integration.json),
  clean/upgrade/real PostgreSQL/Redis: all 33 commands PASS, cleanup complete;
  Spring 220 passed plus four conditional installer entries; separate query-plan
  test passed. Python 579 passed, 108 conditional service skips accounted for;
  131 required service cases ran without skips. See [the exact accounting](reports/integration-review-20260906-r17/summary.md).
  Subsequent [Linux cross-user receipt access](../operations/identity_receipts/evidence/local-v29-readers-r1/report.json)
  passes 13 actual UID/GID checks, plus 193 related tests without skips.
- **D**: [representative V29/R30 independent reconciliation](reports/representative-frozen-v29-r2/verification.json):
  actual canonical facts and complete migration account histories; unchanged
  legacy endpoint oracle; 3,308 overview rows, 19,776 period cells and 1,611,604
  comparison result rows. Every exact digest equal, zero critical mismatches.
- **B**: [production browser contracts](../frontend/test-results/routes-production-v28-r1.json),
  48/48; frontend lint/typecheck/client drift/build and 94 leaf unit cases PASS.
  The unchanged Next build also serves V29.
- **F**: [actual authenticated browser forms](../frontend/evidence/manage-flow-v29-r2/report.json),
  14/14 on a separate V29 database: readback, stale CAS, CSRF, native ID, matrix,
  enable/disable and confirmed delete.
- **V**: final unmasked V29/R30 [pages](../frontend/evidence/visual-full-v29-r2-final/report.json)
  176/176 and [chart states](../frontend/evidence/visual-charts-v29-r2-final/report.json)
  98/98 PASS; maximum raw pixel differences 0.2419753086% and 0.3183861952%
  respectively, below 0.5%. Zero masks; maximum actual target CLS 0.0675355450;
  no applicable HTML axe violations. Four native JSON viewer states retain raw
  browser-owned title/lang findings; exact protocol bytes/status pass. Frozen
  clocks/registered CLS observers and source hashes verified for every state.
  [Exact overview semantics](../frontend/evidence/overview-semantic-v29-r2/report.json)
  PASS: all 4,136 ordered cards, 100 pages, 20 platform/period combinations.
- **P**: [V29 final API load](../operations/performance/evidence/public-read-v29-final-r2/report.json):
  hit p95 23.699375 ms/1 SQL, bounded miss 44.284875 ms/3 SQL, 50 samples each;
  constant query count for limits 1–200; final receipt-permission Java artifact.
  [Actual V29 api_read plans](../operations/performance/evidence/query-plans-v29-final-r1/report.json)
  PASS, raw history SELECT denied. [Quiet-host mobile](../frontend/evidence/mobile-performance-v29-r2/report.json) PASS: 10 cold samples × 5 representative routes; maximum initial JS 155,050 bytes, CLS p75 0, worst LCP p75 2,488 ms and INP p75 152 ms. Comparison LCP has only 12 ms lab headroom; production acceptance is separate.
- **H**: [V29 HTTP transition](../operations/http_transition/evidence/local-v29-final-r2/http-transition.json):
  700 requests, zero failures, exact health JSON, seven rejected gates, both S_final
  proofs (R66/R111), actual writer fences and reverse/restart/replay. Four genuine
  Java admin commands plus correlation replays; original collector/admin receipt
  deletion/corruption/restoration and second S_final zero-write repeat verified.
  The unchanged report passes the production predicate's protocol checks;
  external release/operator acceptance remains false. The corrected rollback
  script keeps legacy admin mutations frozen until reverse drain/verify completes;
  87 executable ordering/guard checks and [actual Nginx](../operations/http_transition/evidence/local-v29-nginx-r1/report.json)
  PASS: 159 reads, zero failures, 46 denials; held old request and keepalive drained
  before freeze success. Final HTTP used the identical delivery JAR.
- **R**: [V29 physical DR](../operations/disaster_recovery/evidence/local-v29-final-r1/dr-5e9a768fc9fe.json):
  full restore, WAL/PITR, standby, amcheck/page checksums and primary-off archive
  read. All 12 checks PASS, owned resources removed.
- **C**: [V29 source CSV](reports/integration-review-20260906-r17/legacy-csv-archive-source.json),
  [native collectors](reports/integration-review-20260906-r17/legacy-csv-archive-native.json)
  and [old cold archive](reports/integration-review-20260906-r17/legacy-csv-archive-old_cold.json):
  38 exact-byte cases after actual raw partition removal, all PASS.

## Seven gates per route

Each row requires all seven columns before the route decision changes. N/A is
limited to visual checks for non-UI responses. Performance evidence for bounded
commands is distinguished from measured public-page mobile evidence.

| Use case | 1. Target API | 2. Page/adapter | 3. Contracts | 4. Data/golden | 5. Visual/a11y | 6. Performance | 7. Switch decision |
|---|---|---|---|---|---|---|---|
| `/` | overview | Next SSR filters/sort/continuation | B, I | D; V21/V27 period corrections | V PASS | P API/mobile PASS | NO-GO; legacy |
| `/rating` | rating + keyset | Next SSR, all 207 entities accessible | B, I | D; revision-pinned latest projection | V PASS | P no raw scan/N+1; mobile PASS | NO-GO; legacy |
| `/compare` | compare + bounded candidates | SSR, pinned local chart, selector, linked legends/tooltips | B, I; all four platforms/default/empty/explicit | D; five horizons, both partial modes | V PASS | P bounded query; mobile/JS PASS | NO-GO; legacy |
| `/channels/{id}` | account/children, Telegram namespace | Next detail and bounded publications | B, I; cursors/redirects | D and detail/history oracle | V PASS | bounded keyset; P shared layout/JS baseline | NO-GO; legacy |
| `/platform-accounts/{id}` | account/children, platform namespace | Next platform detail | B, I; cross-namespace cursors | D and detail oracle | V PASS | bounded keyset; P shared layout/JS baseline | NO-GO; legacy |
| `/institutions/{id}` | institution/accounts/publications | Legacy zero/one/many-account behavior | B, I | D; retained disabled non-TG periods V27 | V PASS | bounded children, P no-N+1/shared layout baseline | NO-GO; legacy |
| `/posts/{id}` | publication/history/neighbours/content | Same-snapshot table/chart | B, I; history limits/controls | D; archived text, ordered reactions V24 | V PASS | bounded history; P mobile/JS family PASS | NO-GO; legacy |
| `/platform-posts/{id}` | platform publication/history | Nullable metrics/evidence/table/chart | B, I | D; NULL/zero and same-snapshot | V PASS; owner approved NULL tooltip `—` | bounded history; P mobile/JS family PASS | NO-GO; legacy |
| `GET /manage` | private catalog/session/status | Full SSR forms | B, F, I; Basic/RBAC/stable CSRF | D presentation, catalog tests | V PASS | no-store, bounded pages | NO-GO; legacy |
| `POST /manage/**` | audited catalog commands | CRUD/matrix/native-ID/enable/disable/delete | F, I; origin/CSRF/CAS/replay/rollback | immutable histories, safe URLs/errors | F workflow; V PASS | bounded commands, publisher | NO-GO; legacy |
| Official MRating import/refresh | bounded pinned HTTPS import | Legacy form/result/error redirects | I parser/transport/RBAC; F offline error | Original Python oracle; V23 institution/channel rank separation | V PASS | fetch/body/deadline caps | NO-GO; live-source acceptance external |
| `/health` | legacy/live/ready APIs | Candidate health adapter | H, I freshness/ACL | H exact JSON, nine coherent states | N/A JSON | H mixed health/read p95 42.301 ms | NO-GO; separate approval |
| `/emoji/{emoji_id}` | bounded pinned asset resolver | Legacy URL/body | I; [real DNS/TLS/egress](../operations/https_egress/evidence/local-r1/https-egress.json) | hash/redirect/type/cache parity | custom emoji in V | caps/deadline/cancel verified | NO-GO; live provider/network external |
| `/export/snapshots.csv` | exact compatibility stream | Next legacy URL facade | C, I | V17 lexemes + V22 durable archive facts; exact bytes after raw DROP | N/A exact bytes | bounded cursor/connection | NO-GO; separate approval |
| `/export/posts.csv` | exact posts stream | Same legacy URL facade | C, I | same snapshot, NULL/order/BOM/CRLF/name/escaping | N/A exact bytes | bounded streaming | NO-GO; separate approval |
| Modern export | authenticated durable async jobs | status/download/cancel | I quota/authorization/expiry | one revision during concurrent publish | N/A file API | 150,001 PG rows/one connection; 600,000 rows/64 MiB heap | Candidate; separate from legacy CSV |
| Collector → read → rollback → repeat | four collectors, corrections, publisher | strict S_final/reverse adapter | I, H failure injection and actual fences | D plus H source/reverse hashes | read transition in V/H | H measured transitions, freshness metrics | NO-GO; W CLOSED, live provider/host external |
| Archive/backup/recovery | fence/digest/attestation; maintenance/backup roles | Parquet/WAL/restore/standby producers | I races/corruption/ACL, R recovery | canonical chains/Flyway29/PITR markers | N/A operations | R standby 7.8962 s, full 28.4913 s, PITR 28.0681 s; controlled PITR RPO 0.7227 s | NO-GO for production deletion/transition |

## Pending acceptance and authority boundaries

The NULL-tooltip decision concerns display only: legacy Chart.js formats an
absent delta as `0`; the target shows `—`. Source, API, table and chart data retain
NULL. On 2026-09-06 the owner explicitly chose “Оставить «—» для отсутствующего
значения”. The [decision record](reports/null-tooltip-owner-decision-20260906.json)
binds the actual final-state probe. This display deviation is approved; measured
zero remains zero. The decision does not authorize a production route switch.

Initial S_final history is proved from every original accepted SQLite artifact.
Later post-cutover admin/collector account transitions are independently replayed
from durable original input receipts, bound to actual accepted database commands
and revisions. Missing/corrupt originals fail closed. Full ordered histories,
native ID clearing/re-enrolment and later source snapshots are checked by H and I;
V29 makes admin transitions monotonic even after a future-dated collector interval.
See the [identity authority contract](IDENTITY_HISTORY_RECONCILIATION.md).
Cross-user receipt permissions passed actual Linux tests with separate writers,
reverse, backup and outsider UIDs. Private 0700/0400 and explicit shared
setgid-2750/0440 storage are both checked; readers cannot change originals and
writers cannot access each other's receipts. This supplements the same-user
HTTP rehearsal; deployed host acceptance remains external.

External acceptance requires production credentials/raw provider captures, an
approved production-size clone/capacity run, deployed Linux systemd/Nginx/TLS,
a separate DR host, encrypted pgBackRest and remote immutable archive retention,
and named product/data/operations approvals. Synthetic local rehearsal is not
that acceptance. No production operation was performed.
