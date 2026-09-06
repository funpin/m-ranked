# Isolated HTTP upstream and writer transition

Status: **pass**. Actual legacy FastAPI and packaged Spring API; loopback proxy.

Route: legacy → target → restarted legacy → target. 290 real HTTP samples, 0 failed health/read samples; p95 22.916 ms.

| Transition | Route switch seconds | Verified seconds |
|---|---:|---:|
| legacy → target | 0.187078 | 0.623947 |
| target → legacy | 0.176767 | 0.455104 |
| legacy → target | 0.16109 | 0.500944 |

Three rejected gates preserved routing and writer ownership. SQLite write locks and database-scoped PostgreSQL CONNECT grants rejected the inactive collector, verified by real rolled-back writes. Reverse S0/catch-up/S-final, target collectors, drain/verify/stop and forward identity replay share the same fixture.

S-final admission includes the independent projection and complete identity-history proofs, bound to the same source SHA-256 and dataset revision.

Health samples preserve the legacy shape with explicit collector freshness. Target readiness gates admission; reads keep their last published revision while collectors advance raw data. All disposable Compose resources and application processes were removed.

Production acceptance remains false: no production load balancer, TLS, cross-host network, or traffic load was exercised.
