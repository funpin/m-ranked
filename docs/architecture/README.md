# Архитектура M-Ranked

Этот каталог — архитектурный пакет проекта. Он фиксирует фактическое состояние
(`AS-IS`) и предлагаемую целевую архитектуру (`TO-BE`). Целевые схемы и ADR со
статусом `Proposed` не описывают уже реализованное поведение: они становятся
обязательными только после принятия соответствующего ADR.

## Карта пакета

| Представление  | Назначение                                         | Исходник                                                 |
| -------------- | -------------------------------------------------- | -------------------------------------------------------- |
| C4 Level 1     | Контекст системы и внешние участники               | [System Context](c4/01-system-context.puml)              |
| C4 Level 2     | Текущие контейнеры                                 | [Containers AS-IS](c4/02-containers-current.puml)        |
| C4 Level 2     | Целевые контейнеры                                 | [Containers TO-BE](c4/03-containers-target.puml)         |
| C4 Level 3     | Компоненты Spring API                              | [API](c4/04-components-api.puml)                         |
| C4 Level 3     | Компоненты collectors                              | [Collectors](c4/05-components-collectors.puml)           |
| C4 Level 3     | Аналитика и расчеты                                | [Analytics](c4/06-components-analytics.puml)             |
| C4 Level 3     | Кэш и инвалидация                                  | [Cache](c4/07-components-cache.puml)                     |
| C4 Level 3     | Административный контур                            | [Admin](c4/08-components-admin.puml)                     |
| C4 Level 4     | Кодовая модель formula engine                      | [Formula engine](c4/09-code-formula-engine.puml)         |
| C4 Level 4     | Кодовая модель collector pipeline                  | [Collector pipeline](c4/10-code-collector-pipeline.puml) |
| ERD            | Фактическая SQLite, schema version 14              | [Current SQLite](erd/current-sqlite.puml)                |
| ERD            | Целевая PostgreSQL                                 | [Target PostgreSQL](erd/target-postgresql.puml)          |
| Deployment     | Целевое развертывание на двух серверах             | [Deployment](views/deployment.puml)                      |
| Data lifecycle | Путь данных от наблюдения до удаления              | [Data lifecycle](views/data-lifecycle.mmd)               |
| Collection     | Telegram: MTProto/public web                       | [Telegram](sequences/collection-telegram.mmd)            |
| Collection     | VK API                                             | [VK](sequences/collection-vk.mmd)                        |
| Collection     | MAX user API                                       | [MAX](sequences/collection-max.mmd)                      |
| Collection     | Rutube API                                         | [Rutube](sequences/collection-rutube.mmd)                |
| Cache          | Публикация ревизии и инвалидация                   | [Cache invalidation](sequences/cache-invalidation.mmd)   |
| DR             | Репликация, backup и restore                       | [Replication and backup](views/replication-backup.puml)  |
| Migration      | Переезд SQLite/FastAPI → PostgreSQL/Spring/Next.js | [Migration and cutover](sequences/migration-cutover.mmd) |
| Security       | Trust boundaries и реестр угроз                    | [Threat model](security/threat-model.md)                 |

## Решения

- [ADR-001: модульный монолит](adr/ADR-001-modular-monolith.md)
- [ADR-002: PostgreSQL](adr/ADR-002-postgresql.md)
- [ADR-003: Next.js](adr/ADR-003-nextjs.md)
- [ADR-004: политика хранения](adr/ADR-004-retention.md)
- [ADR-005: семантика метрик](adr/ADR-005-metric-semantics.md)
- [ADR-006: терминология аномалий](adr/ADR-006-anomaly-terminology.md)

## Область системы

M-Ranked наблюдает опубликованные социальными платформами счетчики. Система не
имеет доступа к внутренним журналам платформ и не устанавливает происхождение
каждой реакции или просмотра. Она хранит наблюдения, рассчитывает воспроизводимые
агрегаты, сопоставляет сценарии рейтинга и показывает статистические аномалии.

В целевой границе системы находятся:

- публичный сайт и API;
- админка и аудит административных действий;
- сбор Telegram, VK, MAX и Rutube;
- нормализация, проверка качества и история измерений;
- агрегаты, формулы рейтинга и признаки аномалий;
- кэш, экспорт, мониторинг, резервное копирование и восстановление.

Не входят в границу: управление социальными платформами, доказательство
намеренной накрутки, официальный расчет M-Рейтинга и учет студентов в системах
университетов.

## Как смотреть и собирать

Mermaid-файлы открываются непосредственно в GitHub, GitLab и большинстве IDE с
поддержкой Mermaid. Для локальной проверки можно использовать Mermaid CLI:

```bash
mmdc -i docs/architecture/views/data-lifecycle.mmd -o /tmp/data-lifecycle.svg
```

PlantUML-файлы используют стандартную библиотеку C4-PlantUML через
`!include <C4/...>`. Их можно открыть расширением PlantUML для IDE или собрать:

```bash
plantuml -tsvg docs/architecture/**/*.puml
```

Для воспроизводимой CI-сборки следует закрепить версии PlantUML и Mermaid CLI,
а сгенерированные SVG публиковать как artifact, не коммитить как источник.

Текущий пакет проверен парсерами PlantUML `1.2025.4` (включая C4 standard
library) и Mermaid `11.10.1`.

## Соглашения

- Все времена — `timestamptz` в UTC; часовой пояс применяется только при выводе.
- `NULL` означает «измерение отсутствует или неприменимо», а `0` — измеренный ноль.
- Связи на схемах помечены протоколом и назначением, а не только направлением.
- Красная граница — недоверенная внешняя зона; синяя — production; зеленая — DR.
- `publication_metric_snapshot` — наблюдение накопительного счетчика, не событие.
- Единственный владелец DDL целевой БД — Flyway в backend-модуле.
- Коллекторы и API выпускаются одним release train и не являются независимыми
  микросервисами.

## Проверка актуальности

Архитектурный пакет пересматривается при каждом изменении:

- границ модулей или владельца таблиц;
- семантики метрик и формул;
- сроков хранения;
- внешних API и способов авторизации;
- topology production/DR;
- RPO, RTO или модели угроз.
