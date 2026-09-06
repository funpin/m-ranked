# Isolated HTTP upstream and writer transition

Status: **pass**. Actual legacy FastAPI and packaged Spring API; loopback proxy.

Route: legacy → target → restarted legacy → target. 700 real HTTP samples, 0 failed health/read samples; p95 42.301 ms.

| Transition | Route switch seconds | Verified seconds |
|---|---:|---:|
| legacy → target | 0.235808 | 0.828662 |
| target → legacy | 0.207436 | 0.47385 |
| legacy → target | 0.264157 | 0.589266 |

Rejected gates, including missing/corrupt original identity receipts, preserved routing and writer ownership. SQLite write locks and database-scoped PostgreSQL CONNECT grants rejected the inactive collector, verified by real rolled-back writes. Reverse S0/catch-up/S-final, target collectors, drain/verify/stop and forward identity replay share the same fixture.

Both S-final admissions include independent projection and complete identity-history proofs bound to their original source SHA-256 and dataset revision. The second follows actual native-ID/name changes, reverse sync and legacy restart; its exact repeat writes zero rows at an unchanged revision.

Health samples preserve the legacy shape with explicit collector freshness. Target readiness gates admission; reads keep their last published revision while collectors advance raw data. All disposable Compose resources and application processes were removed.

Production acceptance remains false: no production load balancer, TLS, cross-host network, or traffic load was exercised.
