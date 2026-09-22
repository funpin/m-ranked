# Архитектура M-Ranked

Фактический production-стек: Next.js, FastAPI, платформенные Python-сборщики,
anomaly worker и PostgreSQL 18.

## Описания

- [конвейер сборщиков](collector-pipeline.md);
- [модуль анализа](analyze-module.md);
- [профили развёртывания](deployment-topologies.md);
- [протокол передачи](raw-data-transfer.md);
- [модель угроз](security/threat-model.md);
- [политика зависимостей](security/dependency-policy.md).

## Decisions

- [ADR-001: modular monolith](adr/ADR-001-modular-monolith.md);
- [ADR-002: PostgreSQL](adr/ADR-002-postgresql.md);
- [ADR-003: Next.js](adr/ADR-003-nextjs.md);
- [ADR-004: retention](adr/ADR-004-retention.md);
- [ADR-005: metric semantics](adr/ADR-005-metric-semantics.md);
- [ADR-006: anomaly terminology](adr/ADR-006-anomaly-terminology.md);
- [ADR-007: live bounded reads](adr/ADR-007-live-bounded-reads.md);
- [ADR-008: no Redis](adr/ADR-008-no-redis.md) — отменён ADR-011;
- [ADR-009: collector phase arbiter](adr/ADR-009-collector-phase-arbiter.md);
- [ADR-010: профили развёртывания и граница raw/ready](adr/ADR-010-deployment-profiles.md);
- [ADR-011: общий кэш ответов](adr/ADR-011-shared-response-cache.md);
- [ADR-012: collect и persist как разные фазы](adr/ADR-012-collect-persist-phases.md);
- [ADR-013: размещение сборщиков и слияние наблюдений](adr/ADR-013-collector-placement-and-merge.md).

## Планы

- [переход к двум профилям развёртывания](two-server-migration-plan.md) — принят, не реализован.

M-Ranked хранит наблюдаемые публичные счётчики и качество измерений. Он не
доказывает происхождение реакции/просмотра и не делает вывод о намеренной
накрутке. Database roles отделяют public reads, admin writes, ingestion,
analysis, maintenance, backup и outbox marking.
