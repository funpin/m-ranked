# Эксплуатация

M-Ranked работает как единый Python/PostgreSQL/Next.js release. Переходного
SQLite-контура, Spring, Redis и reverse-sync в текущем релизе нет.

## Процессы

- `m-ranked-target-api.service` — FastAPI и встроенный outbox marker;
- `m-ranked-target-web.service` — Next.js;
- `m-ranked-target-collector@{telegram,vk,max,rutube}.service` — независимые сборщики;
- `m-ranked-target-anomaly-analysis.service` — анализ аномалий;
- maintenance, backup и restore timers из `operations/systemd/`.

API использует отдельные роли `api_read`, `api_write_admin` и
`outbox_worker`. Сборщики используют только `collector_ingest`.
Пароли передаются через systemd credentials или libpq passfile, не через
аргументы процессов.

## Сборщики

```bash
.venv/bin/python -m collector_target --platform telegram
.venv/bin/python -m collector_target --platform vk
.venv/bin/python -m collector_target --platform max
.venv/bin/python -m collector_target --platform rutube
```

Каждый процесс имеет отдельный lease, лимит памяти и platform-scoped credential.
Telegram поддерживает public web, Web K и MTProto; MAX и Telegram сохраняют
свои session-файлы как отдельные зашифрованные runtime-секреты.

В `phased` mode поверх platform lease действует один общий PostgreSQL advisory
lease полного цикла. Durable request checkpoints задают fairness, а пропущенные
UTC-слоты схлопываются в один запуск. `legacy` сохраняет прежние offsets как
оперативный rollback, `shadow` проверяет решения scheduler без provider calls.
Архитектура, capacity gate и rollout описаны в
[ADR-009](architecture/adr/ADR-009-collector-phase-arbiter.md).

## База и кэш

Схема создаётся из `db/migrations/*.sql`; текущий contract id —
`live-read-2026-09-13`. Public reads выполняются непосредственно по bounded
SQL. FastAPI держит небольшой LRU-кэш в памяти и сбрасывает его по PostgreSQL
`LISTEN/NOTIFY`. Потеря уведомления не влияет на корректность: ключ включает
ревизию набора, TTL ограничен.

Подробные процедуры: [deploy](../operations/runbooks/DEPLOY.md),
[backup/restore](../operations/runbooks/BACKUP_RESTORE.md),
[аварийный откат приложения](../operations/runbooks/ROLLBACK.md).
