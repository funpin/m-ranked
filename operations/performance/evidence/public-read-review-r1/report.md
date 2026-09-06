# Public read performance rehearsal

Gate: **PASS**. Production acceptance: **false**.

Local synthetic representative corpus; API JSON and legacy HTML are reported separately.

- cacheHit: p95 21.90 ms.
- boundedMiss: p95 46.66 ms.
- legacyHtmlBefore: p95 19.28 ms.

Every check:
- exactFlywayManifest: PASS
- representativeData: PASS
- managementPortIsolated: PASS
- boundedPageHas200Rows: PASS
- cacheHitP95: PASS
- cacheHitConstantQueryCount: PASS
- cacheHitCachePathVerified: PASS
- boundedMissP95: PASS
- boundedMissConstantQueryCount: PASS
- boundedMissCachePathVerified: PASS
- noNPlusOneAcrossPageSizes: PASS
- etag304: PASS
- revisionDidNotChange: PASS
