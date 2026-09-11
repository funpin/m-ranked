# Архитектура M-Ranked

Фактический production-стек: Next.js, FastAPI, платформенные Python-сборщики,
anomaly worker и PostgreSQL 18.

## Представления

- [System context](c4/01-system-context.puml);
- [containers](c4/03-containers-target.puml);
- [collectors](c4/05-components-collectors.puml);
- [PostgreSQL ERD](erd/target-postgresql.puml);
- [data lifecycle](views/data-lifecycle.mmd);
- [deployment](views/deployment.puml);
- [backup and replication](views/replication-backup.puml);
- [threat model](security/threat-model.md).

## Decisions

- [ADR-001: modular monolith](adr/ADR-001-modular-monolith.md);
- [ADR-002: PostgreSQL](adr/ADR-002-postgresql.md);
- [ADR-003: Next.js](adr/ADR-003-nextjs.md);
- [ADR-004: retention](adr/ADR-004-retention.md);
- [ADR-005: metric semantics](adr/ADR-005-metric-semantics.md);
- [ADR-006: anomaly terminology](adr/ADR-006-anomaly-terminology.md);
- [ADR-007: live bounded reads](adr/ADR-007-live-bounded-reads.md);
- [ADR-008: no Redis](adr/ADR-008-no-redis.md).

M-Ranked хранит наблюдаемые публичные счётчики и качество измерений. Он не
доказывает происхождение реакции/просмотра и не делает вывод о намеренной
накрутке. Database roles отделяют public reads, admin writes, ingestion,
analysis, maintenance, backup и outbox marking.
