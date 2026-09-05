# Промт для миграции M-Ranked на целевой стек

Скопируй весь текст ниже в задачу агенту разработки, имеющему доступ к репозиторию
M-Ranked. Промт рассчитан на поэтапную реализацию, а не на подготовку ещё одного
архитектурного документа.

---

Ты — ведущий инженер миграции M-Ranked. Выполни контролируемую миграцию проекта
с текущего стека на целевой, сохранив все пользовательские возможности, внешний
вид сайта, URL и все существующие production-данные. Работай непосредственно в
репозитории, вноси код, тесты, миграции, эксплуатационные файлы и документацию.
Не останавливайся на scaffolding, макетах, псевдокоде или плане: каждая фаза
должна завершаться работающим, проверенным и обратимо развёртываемым срезом.

## 1. Источники истины и приоритет решений

Перед любыми изменениями полностью прочитай:

- `AGENTS.md` и все инструкции, на которые он ссылается;
- `README.md`, `ARCHITECTURE_AUDIT.md`, `MULTIPLATFORM.md`, `ROADMAP.md`;
- весь каталог `docs/architecture`, в особенности ADR-001—ADR-006, текущую и
  целевую ERD, C4-схемы, data lifecycle, cache invalidation, deployment,
  replication/backup и `sequences/migration-cutover.mmd`;
- текущие `app/database.py`, `app/analytics.py`, `app/platform_analytics.py`,
  `app/web/app.py`, collectors, scheduler, templates, static assets, deploy units
  и все тесты.

Для этой задачи считай целевой стек из `docs/architecture` утверждённым. Статус
`Proposed` в ADR не является основанием оставить миграцию нереализованной. При
противоречии общий `ARCHITECTURE_AUDIT.md` используй как обоснование и описание
AS-IS, а конкретные TO-BE ADR/C4/ERD из `docs/architecture` — как приоритетную
целевую спецификацию. Не меняй смысл метрик или формулы под видом миграции.

Перед работой проверь состояние Git. Не удаляй и не перезаписывай чужие или
несвязанные изменения. Зафиксируй фактический baseline: команды запуска,
количество и результат тестов, список маршрутов и query-параметров, HTML/API
контракты, SQL-схему SQLite, размеры репрезентативных данных и ключевые времена
ответа. Не полагайся на указанное в старом аудите количество тестов — измерь его.

## 2. Текущее и целевое состояние

AS-IS:

- Python 3.11+, FastAPI/Uvicorn;
- server-side Jinja2, обычные CSS/JS, Chart.js через CDN;
- SQLite/WAL, `sqlite3`, raw SQL, собственные schema migrations;
- отдельные legacy Telegram-таблицы и generic-модель VK/MAX/Rutube;
- Python `asyncio` collectors для Telegram, VK, MAX и Rutube;
- web и collector уже работают отдельными systemd units за Nginx/HAProxy;
- UI пересчитывает часть аналитики из raw snapshots, а `/compare` содержит N+1;
- текущий CSV export сначала материализует данные в памяти;
- архивирование/retention покрывает платформы неравномерно.

TO-BE:

- один монорепозиторий и единый release train, модульный монолит, не набор
  преждевременных микросервисов;
- Next.js App Router + TypeScript + React, SSR/Server Components по умолчанию,
  Client Components только для графиков, фильтров и реальной интерактивности;
- Java/Spring Boot/Spring MVC backend с versioned `/api/v1`, OpenAPI,
  ports-and-adapters и модулями `catalog`, `ingestion`, `analytics`, `rating`,
  `admin`, `query`, `cache`, `operations`;
- PostgreSQL — единственный authoritative transactional store; Flyway —
  единственный владелец DDL; аналитический SQL через jOOQ/JdbcClient;
- Python collectors сохраняются, получают canonical pipeline,
  `ObservationRepository` на psycopg и отдельные systemd units по платформам;
- Redis/Caffeine/HTTP/Next cache с ключом dataset revision; потеря Redis event
  не влияет на корректность, потому что authoritative revision хранится в PG;
- полные raw observations append-only; read-модели и агрегаты полностью
  перестраиваемы;
- Parquet + Zstandard + manifest/checksum как cold archive;
- Nginx, structured logs, Prometheus-compatible metrics, backup + WAL archive,
  отдельный DR standby согласно архитектурному пакету.

Закрепи в lock/build-файлах совместимые поддерживаемые версии runtime и
зависимостей. Не делай случайный upgrade существующих collectors и внешних API
клиентов, если он не нужен для миграции.

## 3. Непереговорные инварианты

### 3.1. Функциональный паритет

Нельзя потерять, упростить, заглушить или незаметно изменить ни одну рабочую
возможность. Составь трассируемую матрицу `legacy route/use case -> target API ->
target page -> tests -> migration phase`. В неё должны войти как минимум:

- `/`, `/rating`, `/compare`, `/manage`, `/health`, `/emoji/{emoji_id}`;
- `/channels/{id}`, `/posts/{id}`, `/institutions/{id}`,
  `/platform-accounts/{id}`, `/platform-posts/{id}`;
- `/export/snapshots.csv`, `/export/posts.csv`;
- все существующие POST-команды `/manage/**`;
- фильтры, поиск, сортировка, направления сортировки, периоды `3h`, `1d`, `7d`,
  `30d`, переключатель `all/telegram/vk/max/rutube`, pagination, пустые состояния,
  ошибки и redirects;
- сбор Telegram через текущие доступные режимы, VK, MAX и Rutube, их rate limits,
  concurrency, адаптивное расписание, deletion confirmation, joint posts,
  Telegram albums, reposts, custom emoji, комментарии и reaction breakdown;
- управление вузами и аккаунтами, enable/disable/delete/native-id, импорт
  официального M-Рейтинга, health/freshness, backup и пользовательские CSV.

Сохрани legacy URL. Так как целевая доменная identity — UUID, создай явную
таблицу aliases/legacy identifiers и разрешай старые integer IDs без изменения
публичных ссылок и закладок. Новые внутренние UUID не должны просочиться в старый
URL-контракт без отдельного совместимого решения.

### 3.2. Неизменная семантика аналитики

До отдельного продуктового изменения бит-в-бит/численно воспроизведи текущие
правила на golden dataset:

- все моменты в storage — UTC, отображение — `Europe/Moscow`;
- окно периода имеет форму `(start, end]`;
- `0` — измеренный ноль, `NULL` — нет/не поддерживается/непригодно; никогда не
  превращай `NULL` в ноль;
- delta/rate рассчитываются из raw накопительных snapshots и не считаются
  первичным фактом;
- synthetic baseline разрешён только при текущих условиях полноты и всегда
  помечен как synthetic;
- incomplete/forced-incomplete history остаётся неполной задним числом;
- временная точка сравнения использует последний замер, известный на этот час,
  и не переносит будущий замер назад;
- cohort линии сравнения фиксирован на всём горизонте;
- сначала считается показатель каждой публикации, затем медиана; среднее и
  медиана не взаимозаменяемы;
- пропущенные/неопределённые интервалы не интерполируются;
- отрицательные значения, reset counters, platform capabilities, albums,
  joint posts и reposts обрабатываются по ADR-005 и текущему проверенному
  поведению;
- миграция не совмещается с новой формулой, новым cohort или изменением
  трактовки метрик.

Для каждого агрегата API возвращай `asOf`, dataset revision, sample size,
coverage и quality, но внедряй их в UI так, чтобы не ломать зафиксированный
визуальный вид. Если новый обязательный смысл нельзя показать без изменения
макета, сначала зафиксируй проблему и предложи минимальный совместимый вариант;
не выполняй самовольный redesign.

### 3.3. Визуальный паритет UI

Next.js должен воспроизвести текущий сайт визуально, а не интерпретировать его
заново. Запрещены redesign, смена шрифтов, цветов, размеров, сетки, порядка
блоков, текстов, иконок, графиков, breakpoints, состояний форм и таблиц под
предлогом «современного frontend».

До переноса страницы:

1. Подними legacy web на стабильном golden dataset и фиксированном времени.
2. Сохрани эталонные Playwright screenshots и DOM/semantic snapshots для всех
   маршрутов, платформ, основных периодов и состояний на desktop и mobile.
3. Зафиксируй computed styles/дизайн-токены: typography, цвета, spacing,
   widths, borders, shadows, sticky headers, scroll containers и chart options.
4. Переиспользуй существующие `logo.png`, `favicon.png` и остальные официальные
   assets без генеративной перерисовки.
5. Сравни Next.js и legacy в одном browser/runtime. Базовый порог visual diff —
   не более 0.5% отличающихся пикселей на странице; любое исключение должно быть
   адресно замаскировано только для динамического значения и объяснено. Нельзя
   маскировать целый график, таблицу или страницу.
6. Проверь keyboard navigation, focus, hover, tooltip, responsive layout,
   sticky table headers и отсутствие CLS.

Chart-библиотеку закрепи в lockfile и загружай локально/динамически только на
маршрутах с графиком. Не оставляй runtime CDN dependency. SSR HTML должен
содержать основной контент страницы до выполнения browser JavaScript.

## 4. Целевая модель данных и обязательные read-модели

Реализуй целевую ERD через Flyway, включая schemas, enum/check constraints,
FK/unique/indexes, роли и grants. Соблюдай следующие правила:

- UUID — business identities, bigint — высокообъёмные observation rows;
- `timestamptz` для моментов времени, `date` только для календарных дат;
- counters — bigint, rating values — numeric с явным rounding;
- observations append-only; correction — новая запись с lineage;
- common metrics — nullable typed columns, platform-specific evidence — JSONB
  или дочерняя таблица, но не EAV для всех метрик;
- `publication_metric_snapshot` партиционируется по месяцу публикации в точном
  соответствии с ADR-002/ERD; partition key входит в PK/FK/idempotency;
- запись observation, collection lineage и dataset revision атомарна;
- collector role не имеет DDL и доступа к чужим таблицам; runtime API role не
  имеет migration privileges;
- raw payload отделён от обычных query paths.

Не заставляй UI сканировать raw snapshots. Добавь и используй read-модели:

1. `publication_latest` — последняя пригодная точка каждой публикации по каждой
   метрике, время наблюдения, quality и revision.
2. `publication_hourly` — last-known-at-or-before-hour точки публикации с
   synthetic/incomplete/uncertain flags. Она должна воспроизводить текущую
   почасовую логику без переноса будущих значений назад.
3. `institution_daily_metrics` и `institution_monthly_metrics` — показатели
   вуза по platform/metric/aggregation с window, sample size, coverage, quality,
   as-of и dataset revision.
4. `institution_period_metrics` — готовые результаты для часто используемых
   периодов `3h/1d/7d/30d`; произвольный допустимый период рассчитывай только из
   bounded hourly/daily projections, не из полного raw history.
5. При необходимости отдельную projection для fixed-cohort comparison, чтобы
   `/compare` выполнялся одним set-based запросом/небольшим фиксированным числом
   запросов, а не запросом на вуз и затем на каждую публикацию.

Read-модели могут быть projection tables/materialized views, но у них должны
быть: явный владелец, incremental update после commit, idempotent rebuild с
нуля, revision/freshness, индексы под реальные query shapes и тест равенства с
golden legacy calculation. Публикуй новую revision только после атомарного
commit данных и projections либо явно показывай состояние rebuilding. Redis
содержит только производный cache; холодный/пустой Redis не меняет результат.

Для ключевых страниц добавь production-like `EXPLAIN (ANALYZE, BUFFERS)` и
query-count tests. Запрещены unbounded scan всех hot snapshots на HTTP-request,
N+1 и загрузка всего CSV в память.

## 5. Мост SQLite → PostgreSQL без потери данных

Мост — отдельный тестируемый продукт миграции, а не одноразовый SQL-скрипт.
Реализуй idempotent importer/bridge с dry-run, resume, checkpoints, structured
report и безопасным повторным запуском. Он никогда не удаляет данные источника.

### 5.1. Точное сопоставление legacy-данных

Создай и утверди mapping matrix до импорта:

| SQLite source | PostgreSQL target/правило |
|---|---|
| `institutions` | `catalog.institution`; все фиксированные поля M-Рейтинга также разворачиваются в исторические `official_rating_observation` с пометкой legacy source |
| `platform_accounts` + `channels` | единый `platform_account`, `account_identity_history`, текущий/исторический account snapshot; существующая связь `channels.platform_account_id` имеет приоритет, дубли не создаются |
| `platform_posts` + `posts` | единая `publication`; natural keys и legacy IDs получают постоянное UUID mapping |
| `post_messages` | все Telegram album member IDs становятся identities одной logical publication, не отдельными публикациями |
| `platform_snapshots` + `reaction_snapshots` | `publication_metric_snapshot`; reaction JSON — `reaction_breakdown`; `NULL`, zero, timestamps, bucket, uncertainty и synthetic semantics сохраняются |
| deletion/missing fields | `deletion_observation` и итоговый `deleted_at`, включая последовательность подтверждений насколько она представлена в legacy |
| `subscriber_*` в accounts/channels | `account_metric_snapshot`; нельзя выдумывать отсутствующую историю |
| `raw_json`, `raw_state_json` | lineage/raw migration evidence согласно retention; до полного acceptance ничего необратимо не удаляется |
| `delta_*`, `rate_per_hour`, `spike` | не становятся raw facts; пересчитываются в versioned projection, а исходные legacy значения сохраняются в migration evidence до доказанного паритета |
| `app_state` | явно сопоставленные operational checkpoints/freshness; неизвестные ключи сохраняются как migration evidence, не теряются молча |
| `schema_migrations` | provenance версии источника; не подмешивается в Flyway history |

Каждая колонка текущей SQLite schema version должна иметь один из статусов:
`mapped`, `derived-and-verified`, `preserved-as-evidence`, `intentionally
deprecated-after-acceptance`. Ни одна колонка не может исчезнуть без
зафиксированного решения и проверки.

Создай изолированную migration schema/таблицы как минимум для:

- migration batch: source file identity, SQLite schema version, started/finished
  time, status, tool version, source SHA-256;
- постоянного `source_table + source_pk -> target_type + target_uuid/bigint`
  mapping;
- checkpoints/high-water marks;
- reconciliation results и выявленных расхождений;
- legacy row hash/evidence для полей, не имеющих прямого canonical target.

UUID генерируй детерминированно из неизменяемого migration namespace и полного
legacy natural key либо один раз сохраняй mapping до записи зависимостей.
Повторный запуск на том же source обязан получить те же identities. Не
используй текущий username как единственную identity, если доступен native ID.

### 5.2. Online backfill и catch-up

Реализуй последовательность:

1. Проверенный online backup SQLite `S0` через SQLite Backup API, `quick_check`
   и SHA-256. Оригинальный production-файл не копируй обычным `cp` во время
   записи.
2. Initial load `S0` в пустую PostgreSQL через bounded batches и транзакции.
3. Пока legacy collector работает, выполняй catch-up append-only таблиц по
   устойчивому high-water mark, а mutable rows — по row hash/upsert. Для hard
   delete/update без надёжного `updated_at` используй небольшой append-only
   change journal/outbox или эквивалентный механизм, атомарный с legacy write.
   Если добавляется SQLite trigger journal, сначала протестируй его overhead,
   idempotency, cascades и восстановление; не сохраняй в журнал secrets.
4. Все события replay выполняй по монотонной sequence и делай идемпотентными.
   Финальный полный hash reconciliation обязателен независимо от journal.
5. Подними Spring API в shadow mode и Next.js на непубличном route/upstream.
6. Сравнивай normalized legacy и target ответы на frozen golden data и на
   текущем shadow dataset. Динамические `now`, request ID и порядок JSON полей
   нормализуй; реальные числовые расхождения не маскируй.

Если надёжный online journal невозможно добавить без риска, не имитируй CDC:
используй повторные полные идемпотентные проходы по базе текущего размера и
короткую финальную остановку writer. Корректность важнее «нулевой паузы».

### 5.3. Reconciliation — жёсткий gate

После initial load, каждого catch-up и перед cutover сформируй машинно читаемый
JSON и человекочитаемый Markdown report со сверкой:

- row counts по каждой исходной таблице, target entity и platform;
- distinct natural keys и отсутствие дублей;
- orphan/FK/constraint checks;
- min/max published/observed/created timestamps;
- counts и суммы по `views/reactions/comments/shares/subscribers`;
- отдельно количество `NULL`, измеренных нулей, отрицательных переходов,
  synthetic, incomplete, uncertain и deleted;
- reaction breakdown count/sum и его соответствие total там, где это обязано
  выполняться текущими правилами;
- albums/joint posts/reposts и количество member identities;
- количество/значения официального M-Рейтинга по вузу, platform и period;
- deterministic hashes по канонически отсортированным строкам/временным рядам;
- агрегаты всех UI-периодов и fixed-cohort curves на golden samples;
- lag/freshness между SQLite и PostgreSQL.

Cutover запрещён при необъяснённом расхождении. `0 vs NULL`, timezone shift,
потеря reaction key, одна пропущенная публикация или дубль — критическая ошибка,
а не допустимая погрешность. Для floating/numeric расчётов зафиксируй rounding и
сравнивай с обоснованным epsilon только там, где точное сравнение невозможно.

### 5.4. Cutover и rollback

Разделяй риск чтения и риск записи:

1. Сначала переключай публичные read-only маршруты по одному через Nginx
   strangler routing, продолжая legacy collection и SQLite→PG catch-up.
2. `/manage` и административные POST оставляй на legacy до готовности полного
   target command/audit/RBAC и обратимой синхронизации; не дели одну форму между
   двумя владельцами записи.
3. В финальном окне останови только legacy writers/admin mutations; legacy
   public reads должны оставаться доступны.
4. Создай и проверь `S-final`, дренируй journal, выполни последний полный
   idempotent pass и reconciliation.
5. Только при зелёном gate запусти target Python collectors против PG и один
   контролируемый collection run. Докажи отсутствие дублей и продвижение
   dataset revision.
6. Атомарно переключи public upstream. Не меняй в этот момент formulas,
   semantics, retention или платформенные adapters.
7. На ограниченное и заранее описанное rollback window включи PG→legacy
   compatibility projection для новых observations/identities, либо другой
   заранее протестированный обратимый механизм. Новые target-only возможности
   в это окно запрещены. Все обратные записи идемпотентны и сверяются.
8. При correctness regression, SLO breach, росте ошибок, freshness lag,
   duplicate ingestion или cache leakage автоматически/по runbook верни Nginx
   на legacy, останови target writers, дренируй compatibility projection и
   перезапусти legacy collectors.
9. Удалять migration bridge, legacy tables/runtime и final SQLite можно только
   после письменного acceptance, истечения rollback window, проверенного backup
   и повторного reconciliation. До этого legacy — recoverable artifact.

Не выполняй production cutover, изменение DNS/upstream или удаление данных без
явной авторизации владельца окружения. Подготовка и проверка кода/runbook входят
в задачу; опасное действие в production — отдельный подтверждаемый шаг.

## 6. Порядок реализации

Двигайся следующими вертикальными фазами. Каждая фаза обязана проходить свои
тесты и сохранять рабочий legacy runtime.

### Фаза A — baseline и compatibility seams

- Создай feature/route/metric inventory и golden fixtures из
  обезличенного/синтетического репрезентативного набора.
- Зафиксируй HTTP contracts, screenshots, CSV headers/order/escaping,
  collector behavior и SQL performance baseline.
- Выдели в Python явные `CollectorAdapter`, `ObservationRepository`,
  `AnalyticsQueryService`, clock и transaction boundaries без изменения
  поведения.
- Удали прямую зависимость platform adapters от SQLite; сначала оставь SQLite
  implementation и докажи все старые тесты.

### Фаза B — PostgreSQL schema, importer и projections

- Добавь воспроизводимый local integration environment с PostgreSQL и Redis;
  tests должны поднимать реальные совместимые сервисы, а не подменять SQL mock.
- Реализуй Flyway migrations с нуля и upgrade test с предыдущей версией.
- Реализуй mapping/import/bridge/reconciliation из раздела 5.
- Реализуй PG repository, partitions, indexes, grants и dataset revision.
- Реализуй read-model rebuild/incremental update и golden equality tests.

### Фаза C — target collectors

- Сохрани platform gateways и доказанное поведение текущих Python collectors.
- Введи canonical normalized DTO/pipeline, collection run/account result,
  scheduled/observed/collected times, quality, source fingerprint и
  idempotency.
- Запускай platform collectors отдельными units/leases; сбой MAX не должен
  остановить Telegram/VK/Rutube.
- Повтор run/batch не создаёт snapshots-дубли; partial failure возобновляется.
- Secrets/session files не попадают в logs, PostgreSQL raw evidence или archive.

### Фаза D — Spring API

- Создай modular backend с чистым domain, application ports и infrastructure
  adapters. Domain не импортирует Spring/JDBC/Redis/HTTP.
- Опиши `/api/v1` через OpenAPI и генерируй/проверяй TypeScript client.
- Реализуй query endpoints для всех legacy pages, keyset pagination, filters,
  sorting, freshness, quality и ETag/Cache-Control.
- Реализуй admin commands с validation, CSRF/auth policy, RBAC
  `ADMIN/EDITOR/VIEWER` по ADR, append-only audit и безопасными errors RFC 9457.
- Реализуй CSV как настоящий bounded streaming/cursor export. Большой export —
  background job со сроком жизни и лимитом; ни API, ни Redis не держат весь
  файл в памяти.
- Health раздели на liveness/readiness и не раскрывай secrets, версии/пути или
  подробности внешнему клиенту.

### Фаза E — Next.js route-by-route

- Переноси страницы по одной, начиная с read-only; каждая получает данные
  только через versioned Spring API и проходит parity/visual/a11y tests.
- Server Components/SSR — default; URL/query params и server-rendered content
  совпадают с legacy.
- Реализуй revision/tag-aware revalidation; admin/auth/health/export не
  попадают в public cache.
- Сохрани все статусы, empty/error states, таблицы, графики, tooltips и формы.
- Для legacy routes, которые ещё не перенесены, Nginx направляет запрос в
  FastAPI; пользователь не видит смешанную или полупустую страницу.

### Фаза F — performance, cache и operations

- Добавь Caffeine L1, Redis L2/PubSub и HTTP validators только после доказанной
  корректности без cache. Cache key включает namespace, revision и полный
  canonical query hash без secrets.
- Lost Pub/Sub event компенсируется чтением authoritative revision из PG.
- Добавь Micrometer/Prometheus и collector metrics: latency, query count,
  freshness, error rates, cache hit, revision lag, rows/day, WAL, table/index/
  partition size, lock waits, Redis/archive spool и disk forecast 5x/10x.
- Обнови systemd units, Nginx/HAProxy, env example и deployment/runbooks с
  наименьшими privileges и независимыми Unix users/roles.
- Реализуй backup, WAL archive, restore verification и DR topology из ADR.

### Фаза G — retention/cold archive и вывод legacy

- Единый retention job покрывает все четыре платформы.
- Перед DROP partition экспортируй Parquet+Zstd, запиши manifest с schema
  version/range/count/min/max/SHA-256, проверь count/checksum/sample read и
  атомарно опубликуй manifest. При ошибке purge останавливается.
- Соблюдай сроки ADR-004; backup, replica и product archive не подменяют друг
  друга.
- Проведи rehearsed cutover и rehearsed rollback на production-like clone.
- Только после acceptance выведи legacy runtime из online, сохрани final SQLite
  и manifests, а удаление выполняй отдельным явно подтверждённым изменением.

## 7. Обязательные проверки

Автоматизируй и запусти минимум:

- все существующие Python unit/integration tests без ослабления assertions;
- PostgreSQL/Flyway/Testcontainers integration tests;
- importer repeat/resume/interruption/out-of-order/delete tests;
- property/golden tests SQLite calculation vs target projection/API;
- OpenAPI compatibility and generated-client check;
- Spring module architecture tests и security tests;
- Next.js typecheck/lint/unit tests;
- Playwright route, form, accessibility и visual regression tests;
- cache isolation/invalidation/ETag/304 tests, включая потерянный Pub/Sub;
- load/performance tests на production-like объёме;
- streaming export memory test;
- backup restore/PITR и cold archive sample-query test;
- end-to-end rehearsals: initial backfill, live catch-up, final cutover,
  rollback, повторный cutover.

Минимальные performance budgets:

- overview API: p95 <= 300 ms на cache hit и <= 1 s на bounded miss;
- Next.js p75 mobile: LCP <= 2.5 s, INP <= 200 ms, CLS <= 0.1;
- route-specific initial JS <= 170 KiB gzip без отдельно принятого исключения;
- query count основных страниц ограничен константой и не растёт с числом вузов
  или публикаций;
- обычный dashboard request не делает unbounded sequential scan hot snapshots;
- export memory остаётся bounded при росте числа строк.

Не «чинить» failing parity test обновлением golden snapshot, пока не доказано,
что старый golden неверен. Любое намеренное отклонение требует отдельного
решения владельца продукта и не входит в техническую миграцию.

## 8. Definition of Done

Миграция готова только если одновременно выполнено всё:

1. Матрица функционального паритета заполнена, все legacy use cases имеют
   target implementation и автоматический тест.
2. Все публичные URL/query params и админские операции сохранены либо имеют
   явно протестированную совместимость/redirect.
3. Visual regression по всем ключевым страницам и breakpoints проходит в
   установленном пороге без широких masks.
4. Полный production-like SQLite импортируется повторяемо; повторный import не
   меняет результат и не создаёт дублей.
5. Reconciliation не содержит необъяснённых расхождений, включая `NULL/0`, UTC,
   reaction breakdown, albums, deletes и M-Рейтинг.
6. UI/API читают latest/hourly/daily/monthly/period projections, а `/compare`
   не содержит N+1 и не сканирует всю raw history.
7. Raw observations остаются source of truth; read-модели полностью
   перестраиваются и дают тот же результат.
8. Target collectors переживают повтор, partial failure и независимый сбой
   одной платформы без потери/дублирования данных.
9. Cache можно полностью очистить/отключить без изменения результата; private
   данные никогда не попадают в public cache.
10. Performance, security, export, backup/restore и retention gates проходят на
    production-like окружении.
11. Cutover и rollback отрепетированы, измерены и описаны пошагово; указан
    оператор, пороги решения, длительность rollback window, RPO/RTO и команды
    проверки каждого шага.
12. Legacy не удалён до явного acceptance; final SQLite backup, checksum,
    mapping и reconciliation reports сохранены.

## 9. Формат работы и финального отчёта

В начале дай короткий фактический план с фазами, зависимостями и gates. Затем
выполняй его автономно. После каждой фазы сообщай: что реализовано, какие тесты
прошли, какой gate закрыт, какие риски остались. Если обнаружено противоречие,
сначала приведи доказательство из кода/данных/ADR и выбери самый обратимый
вариант; спрашивай владельца только когда выбор меняет product semantics,
данные, публичный контракт или требует production-authority.

Финальный отчёт обязан содержать:

- краткий результат и фактический статус каждой фазы;
- ссылки на ключевые файлы, Flyway migrations, OpenAPI, bridge и runbooks;
- полный список выполненных test/build/rehearsal команд и их результаты;
- итог reconciliation с counts/hashes/NULL-zero/time range и найденными
  расхождениями;
- visual regression summary и performance before/after;
- схему текущей маршрутизации и ownership записей;
- пошаговые cutover/rollback команды и измеренные RPO/RTO;
- оставшиеся риски и незавершённые пункты без маскировки их словом «готово».

Не заявляй о завершении, если реализован только каркас, используются mock data,
не пройден production-like import, не проверен rollback или хотя бы одна
существующая возможность/страница временно отсутствует.
