# ADR-001: Модульный монолит вместо преждевременных микросервисов

- Status: **Proposed**
- Date: 2026-09-02
- Owners: architecture / backend
- Related: [target containers](../c4/03-containers-target.puml),
  [target ERD](../erd/target-postgresql.puml)

## Context

Сейчас приложение является Python-монорепозиторием с двумя production-процессами:
web и collector. Они разделяют одну SQLite и общий код. Проект должен получить
Next.js frontend, Spring API, PostgreSQL, несколько платформенных collectors,
аналитику, версионируемые формулы, админку и эксплуатационный контур.

Разбиение на микросервисы сейчас не поддерживается отдельными командами,
независимыми циклами выпуска или доказанной необходимостью масштабировать разные
домены независимо. Оно добавило бы versioned network contracts, брокер,
distributed tracing, повторную доставку, согласованность и несколько схем
deployment прежде, чем эти затраты решают измеренную проблему.

При этом один большой модуль без границ уже создает риски: текущие web,
analytics, administration и SQL сосредоточены в крупных файлах, а Telegram
представлен двумя моделями данных.

## Decision

Развивать M-Ranked как **модульный монолит с единым release train** в одном
монорепозитории.

Логические backend-модули:

- `catalog` — университеты, внешние ID, официальные аккаунты и их история;
- `ingestion` — collection runs, публикации, наблюдения, качество и deletion;
- `analytics` — окна, cohort, агрегаты и anomaly signals;
- `rating` — formula definitions, runs, results, sensitivity и объяснения;
- `admin` — commands, RBAC, verification и audit;
- `query` — публичные projections, pagination, export и API contracts;
- `cache` — revision-aware cache и HTTP validators;
- `operations` — health, metrics, retention и backup coordination.

Физические runtime-процессы допускаются, но не считаются независимыми
микросервисами:

1. `web` — Next.js;
2. `api` — Spring Boot core backend;
3. `collectors` — Python, возможно отдельный systemd unit на платформу;
4. maintenance jobs из того же release.

Все части:

- версионируются и выпускаются согласованно;
- используют одну PostgreSQL database с явными schema/module boundaries;
- совместно проходят contract и migration tests;
- не имеют независимых публичных domain API друг для друга;
- не используют брокер как обязательное условие обычной записи.

Java-модули следуют ports-and-adapters: domain не зависит от Spring, SQL, Redis
или HTTP. Python collectors отделяют platform gateway от canonical pipeline.

Flyway является единственным владельцем DDL. Коллекторы получают минимальные
права только на ingestion-owned tables/functions. Redis Pub/Sub используется
для ускорения cache invalidation, но корректность обеспечивается сохраненной в
PostgreSQL dataset revision; событие можно потерять без потери данных.

## Consequences

Положительные:

- одна транзакция сохраняет observation, lineage и revision;
- локальные вызовы проще, быстрее и надежнее сетевых;
- границы модулей можно тестировать до физического разделения;
- deployment и диагностика подходят небольшой команде и одному серверу;
- отдельные collector units изолируют сбой платформы без микросервисной
  инфраструктуры.

Отрицательные:

- release backend-модулей связан;
- неконтролируемый доступ к чужим таблицам может разрушить границы;
- Java, Python и TypeScript требуют нескольких toolchains;
- масштабирование API и фоновых задач ограничено общей БД.

Контрмеры:

- architecture tests запрещают зависимости против выбранного направления;
- database roles и schema grants отражают владельца данных;
- публичные contracts и golden datasets проверяются в CI;
- package/module API документируются, прямой импорт infrastructure слоя запрещен.

## Alternatives considered

### Микросервисы по каждой социальной сети

Отклонено сейчас: разные платформы имеют мало собственной бизнес-логики, а
общее identity/metric storage требует координации. Изоляция достигается
отдельными units, leases и bulkheads.

### Полностью сохранить FastAPI/Jinja архитектуру

Возможно и дешевле для прототипа, но не выбрано как целевое направление из-за
планируемого строгого API, RBAC, formula lifecycle и Java/Spring компетенции.
Старый runtime сохраняется до завершения контролируемого cutover.

### Event-driven architecture с Kafka

Отклонено: нет измеренного объема или требований независимого replay/ownership,
которые оправдывают отдельный кластер и операционную стоимость.

## Fitness functions

- Domain packages не импортируют Spring/JDBC/Redis/http clients.
- Collector platform adapters не выполняют SQL напрямую, минуя ingestion port.
- Любая запись данных и dataset revision атомарны.
- Один integration environment поднимает всю target-систему без внешнего broker.
- Сбой collector одной платформы не останавливает API и другие collectors.

## Revisit when

Решение пересматривается, если выполняется хотя бы одно условие:

- появились разные команды и независимые release cadences;
- один модуль требует устойчиво отдельного масштабирования, которое нельзя
  обеспечить процессом/очередью jobs;
- требования безопасности или регулирования требуют отдельной data boundary;
- общий PostgreSQL исчерпал измеренный capacity после оптимизации/реплики;
- failure одного модуля нельзя изолировать process boundary и resource limits.
