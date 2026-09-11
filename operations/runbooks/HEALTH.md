# Health and freshness

- `GET /api/v1/health/live` proves process liveness.
- `GET /api/v1/health/ready` proves the database and schema contract are
  available.
- `GET /api/v1/health/freshness` reports bounded per-platform collection
  freshness and the current live dataset revision.
- `GET /api/v1/health/legacy` preserves the frozen compatibility response.

All health responses are `no-store`. Readiness does not wait for a projection
publisher: public data is read directly from canonical tables. A configured
collector with no successful recent run makes freshness unhealthy, while an
in-progress run may retain the previous completed run's timestamp.

Verify after deploy:

```bash
curl --fail http://127.0.0.1:8080/api/v1/health/live
curl --fail http://127.0.0.1:8080/api/v1/health/ready
curl --fail http://127.0.0.1:8080/api/v1/health/freshness
```
