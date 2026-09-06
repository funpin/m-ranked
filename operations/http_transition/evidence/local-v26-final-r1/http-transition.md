# Isolated HTTP upstream and writer transition

Status: **pass**. Actual legacy FastAPI and packaged Spring API; loopback proxy.

Route: legacy → target → restarted legacy → target. 285 real HTTP samples, 0 failed health/read samples; p95 16.033 ms.

| Transition | Route switch seconds | Verified seconds |
|---|---:|---:|
| legacy → target | 0.171731 | 0.701891 |
| target → legacy | 0.210575 | 0.49503 |
| legacy → target | 0.171979 | 0.513887 |

Three rejected gates preserved routing and writer ownership. SQLite write locks and database-scoped PostgreSQL CONNECT grants rejected the inactive collector, verified by real rolled-back writes. Reverse S0/catch-up/S-final, target collectors, drain/verify/stop and forward identity replay share the same fixture.

Health samples preserve the legacy shape with explicit collector freshness. Target readiness gates admission; reads keep their last published revision while collectors advance raw data. All disposable Compose resources and application processes were removed.

Production acceptance remains false: no production load balancer, TLS, cross-host network, or traffic load was exercised.
