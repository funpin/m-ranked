# ADR-002: PostgreSQL как целевая основная база данных

- Status: **Proposed**
- Date: 2026-09-02
- Owners: backend / operations
- Related: [target ERD](../erd/target-postgresql.puml),
  [replication and backup](../views/replication-backup.puml)

## Context

SQLite/WAL хорошо обслуживает прототип, но имеет одного writer, file-based
backup topology и ручные migrations. Система уже хранит две параллельные модели
Telegram, а retention применяется не ко всем platform snapshots. Будущие
нагрузки включают конкурентный ingestion, публичное чтение, оконные функции,
агрегаты, историю формул, admin audit, partition lifecycle и standby на другом
сервере.

Размер данных сам по себе пока не требует распределенной БД или sharding.

## Decision

Использовать поддерживаемую стабильную major-версию PostgreSQL как единственный
authoritative transactional store.

Основные правила:

- один cluster/database, логические schemas по модулям;
- Flyway — единственный механизм DDL и schema history;
- `timestamptz` в UTC для моментов времени, `date` только для календарных дат;
- UUID для business identities, `bigint` для высокообъемных snapshot rows;
- `numeric` и явное округление для rating score; счетчики — `bigint`;
- append-only observations; исправление создается новой записью и lineage;
- monthly range partitions для `publication_metric_snapshot` по денормализованному
  месяцу публикации; partition key входит в composite PK/FK и idempotency
  constraint; `account_metric_snapshot` партиционируется только после измеренной
  необходимости;
- native constraints и idempotency keys защищают от повторного collection;
- JSONB используется для versioned definition/evidence, но не вместо основных
  индексируемых полей;
- raw payload отделен и имеет короткий retention;
- jOOQ/JdbcClient применяются для аналитических SQL; ORM разрешен только для
  простого CRUD без скрытого обхода графа;
- Python collectors используют psycopg и роль с минимальными ingestion grants;
- production имеет asynchronous streaming standby на отдельном сервере;
- backup состоит из base backup + WAL archive и проверяется PITR restore drill.

Sharding, multi-primary и обязательный TimescaleDB не вводятся. Native
partitioning, indexes, materialized/read projections и read replica должны быть
исчерпаны раньше.

## Consistency and ownership

- Запись canonical observation, collection lineage и dataset revision проходит
  в одной транзакции.
- Cache event публикуется после commit; потерянное событие обнаруживается по
  authoritative revision.
- Published formula/run/result immutable.
- Collector не создает и не изменяет таблицы.
- DDL запускается отдельной migration role, которой нет у API runtime.

## Consequences

Положительные:

- конкурентные readers/writers и развитый planner;
- оконные функции и эффективные агрегаты;
- constraints, транзакции и управляемые migrations;
- partition drop вместо массового `DELETE`;
- streaming replication и PITR;
- единый типизированный контракт для Java и Python.

Отрицательные:

- отдельный database process требует RAM, tuning, vacuum и наблюдаемости;
- backup сложнее копирования одного SQLite-файла;
- неверный SQL/индекс способен создать серьезную нагрузку;
- репликация не защищает от логического удаления.

## Alternatives considered

### Продолжить SQLite

Отклонено как target: сохраняет single-writer/host boundary и усложняет
конкурентный ingestion, репликацию и controlled retention. SQLite остается
источником миграции и rollback artifact на переходный период.

### ClickHouse как основная БД

Отклонено: отлично подходит для аналитического чтения, но усложняет
transactional catalog/admin/formula lifecycle. Может появиться позднее как
производная аналитическая копия после измерения нагрузки.

### TimescaleDB с первого дня

Отклонено: расширение не требуется для текущего объема; native PostgreSQL
partitioning уменьшает vendor/operations surface.

## Fitness functions

- Migration прогоняется с нуля и с предыдущей release-версии в CI.
- Повторная ingestion batch не создает дубли.
- План ключевых запросов не выполняет unbounded sequential scan hot snapshots.
- Старую partition нельзя удалить без проверенного archive manifest.
- PITR восстанавливает БД в заданную точку и проходит consistency queries.
- Replica lag, WAL growth, table/index size и disk forecast наблюдаемы.

## Revisit when

- hot dataset или запросы устойчиво превышают capacity оптимизированного
  primary/read replica;
- закон или договор требует географического/tenant-разделения;
- доказан выигрыш отдельного OLAP-store на production-like benchmark;
- RPO/RTO нельзя выполнить выбранным standby/backup topology.
