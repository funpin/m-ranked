# M-Ranked: независимый PostgreSQL/Redis pre-production audit

Дата: 2026-09-08  
Вердикт: **NO-GO**

## 1. Короткий вердикт

Текущий web/API stack нельзя продвигать на production.

| Вопрос | Ответ |
|---|---|
| Ожидаемый рост PostgreSQL после изменений | **NOT PROVEN.** Расчётная гипотеза по старому byte baseline: 0.216–0.288 GiB/сутки. Это не acceptance evidence. |
| Worst-case рост | **NOT PROVEN.** До production-shaped replay capacity следует планировать минимум по старому диапазону 0.9–1.2 GiB/сутки плюс transient publisher/WAL. |
| Основные источники | Старый evidence указывает на publication_metric_snapshot, reaction_breakdown, deletion_observation, их индексы и global projection rebuild. Новый heap/index/TOAST/WAL split не измерен. |
| Страницы и графики в SLO без Redis | **NOT PROVEN.** Synthetic evidence не привязан к final schema и не покрывает требуемую матрицу endpoint/period/platform/concurrency. |
| Publisher безопасен | Manual invocation, oneshot, Restart=no, flock и отсутствие automatic retry loop доказаны. Bounded peak disk и отсутствие блокировок collectors на production-shaped data не доказаны. Capacity guard имеет подтверждённый integer-overflow fail-open defect. |
| Web/API deploy сейчас | Нет. Есть P0 schema/publisher/read-model противоречия и провал memory budget для 2 GiB host. |

Baseline аудита: branch alpha, commit 1e52f415fbdedc15f10e3d992e5126b8b7c92925, divergence +0/-4 относительно origin/alpha. Существующий dirty worktree сохранён. Production, существующая БД, пользовательские данные, исходники, branch и commits не изменялись.

## 2. Блокирующие production проблемы

1. **P0: publication/account API может отдавать старую publication history под новой dataset revision.** Обычный publisher обновляет шесть readiness projections, но исключает analytics.publication_history. JdbcDetailQueries читает history без dataset_revision_id predicate, тогда как JdbcDatasetRevisionProvider признаёт revision текущей по шести другим projections.
2. **P0: чистая final-schema database не завершает первый publisher run.** Таблица ops_and_admin.retention_policy создаётся, но не заполняется. Rebuild требует publication hot_days не меньше 70. Реальный disposable run прошёл capacity guard и завершился exit 75: publication hot retention must be at least 70 days during parity.
3. **P0: production transition gate всё ещё hard-code-ит удалённую Flyway V1–V31 chain.** cutover-preflight.sh и collector_parity_evidence.py требуют schemaVersion 31, 31 migration files, точные hashes и Flyway rows. Это несовместимо с final-schema-only runtime.
4. **P1: publisher capacity arithmetic может fail-open.** При multiplier 9223372036854775807 Bash signed arithmetic дал отрицательный required_bytes, после чего rebuild был разрешён.
5. **P1: frontend превращает bounded Spring endpoints в unbounded fan-out.** Account, institution, publication-history и default comparison получают все continuation pages. Institution page последовательно делает account detail и all-publications requests для каждого account и лишь затем обрезает результат до 500.
6. **P1: отсутствует coherent memory budget для 2 GiB production host.** PostgreSQL ограничен 512 MiB, Redis 80 MiB, API может запросить около 70% host RAM, а web и четыре collectors не имеют systemd MemoryMax.

## 3. Storage baseline

Доступный старый evidence фиксирует БД 5–6 GiB, index share около 46.6%, около 4.04 млн rows/day и 0.9–1.2 GiB/day. Эти числа не были повторно измерены на production и не считаются текущим доказательством.

| Relation | Старые rows/day | Heap/day | Indexes/day | TOAST/day | WAL/day | Причина |
|---|---:|---:|---:|---:|---:|---|
| publication_metric_snapshot | ~854k | NOT PROVEN | NOT PROVEN | NOT PROVEN | NOT PROVEN | Poll snapshots; старый total relation evidence около 3.73 GiB |
| reaction_breakdown | ~1.26m | NOT PROVEN | NOT PROVEN | NOT PROVEN | NOT PROVEN | Несколько reaction rows на snapshot; старый total около 1.02 GiB |
| deletion_observation | ~1.93m | NOT PROVEN | NOT PROVEN | мало/неизвестно | NOT PROVEN | Старый path добавлял каждый present probe; total около 336 MiB |
| account_metric_snapshot | нет надёжного baseline | NOT PROVEN | NOT PROVEN | NOT PROVEN | NOT PROVEN | Subscriber/account changes и heartbeat |
| publication_availability_state | UPDATE на present probe | NOT PROVEN | NOT PROVEN | N/A | NOT PROVEN | Одна current-state row, но остаются update/WAL/vacuum costs |
| publication_availability_event | только transitions | NOT PROVEN | NOT PROVEN | N/A | NOT PROVEN | Missing/returned/deleted audit |
| analytics.dataset_revision | зависит от change batches | NOT PROVEN | NOT PROVEN | N/A | NOT PROVEN | Revision на committed semantic changes |
| ops_and_admin.outbox_event | зависит от revisions/commands | NOT PROVEN | NOT PROVEN | возможно | NOT PROVEN | Durable invalidation и projection requests |
| serving/history projections | зависит от rebuild | NOT PROVEN | NOT PROVEN | возможно | NOT PROVEN | Global delete/insert, temp snapshot и index build |

operations/sql/postgres-storage-audit.sql выполнился без ошибки на чистой final schema, но база была пустой. Поэтому это не evidence для row widths, WAL, HOT ratio, dead tuples, checkpoints и volume growth. Сам audit SQL также не автоматизирует все запрошенные p50/p95 widths и per-iteration WAL/temp/buffer measurements.

Пустая final schema:

- bootstrap около 2.1 s;
- database size около 28–31 MiB;
- около 63 snapshot partitions;
- около 441 partition indexes.

### Suppression

На реальном disposable PostgreSQL прошли обе параметризации test_real_postgres_account_transaction_is_idempotent_and_atomic. Доказаны first snapshot/reactions/revision/outbox, exact replay idempotency, unchanged account suppression, current-state present update, missing/transient/deleted/returned audit, account heartbeat после 24 часов и transaction rollback.

Не доказаны publication heartbeat, изменение каждой quality/evidence/uncertainty semantics, concurrent collectors и production-shaped replay.

Если предположить, что suppression убирает 1.93 млн present observations и 55% snapshot/reaction no-op rows, удаляется около 3.09 млн из 4.04 млн rows/day и остаётся около 0.95 млн rows/day. Линейная экстраполяция старого byte growth даёт 0.216–0.288 GiB/day. Это гипотеза: ширина строк, indexes, current-state updates, bloat, WAL и publisher нелинейны. Gate не более 0.35 GiB/day пока **NOT PROVEN**.

### Storage model

- source_fingerprint остаётся 64-character hex text. BYTEA(32) теоретически экономит около 32 payload bytes на row плюс часть index/varlena overhead, но нужен benchmark на restored copy.
- metric_evidence повторяется как JSONB. Следует сравнить dictionary evidence IDs, normalized evidence set и текущую модель.
- reaction_key хранится text в отдельных rows и индексах. Нужен сравнительный тест dictionary ID, packed JSONB и vertical rows.
- Нельзя удалять B-tree только по idx_scan=0: статистика пустой локальной БД нерепрезентативна.
- Raw retention нельзя сокращать до аудита consumers: publication history, corrections, baseline/recovery и legacy export требуют глубокой истории.
- Безопасная исходная цель: raw 70–90 дней, hourly для всего UI graph horizon, daily long-term, immutable cold archive только после доказанного restore/replay.

## 4. Прогноз database size

Условная отправная точка — 5.5 GiB. Publisher spikes, vacuum и retention не включены.

| Сценарий | 7 дней | 30 дней | 90 дней | 365 дней |
|---|---:|---:|---:|---:|
| Hypothetical expected, 0.216–0.288 GiB/day | 7.0–7.5 | 12.0–14.1 | 24.9–31.4 | 84.3–110.6 |
| Acceptance ceiling, 0.35 GiB/day | 8.0 | 16.0 | 37.0 | 133.3 |
| Старый baseline, 0.9–1.2 GiB/day | 11.8–13.9 | 32.5–41.5 | 86.5–113.5 | 334–443.5 |

Worst-case после текущих изменений — **NOT PROVEN**. Если метрики изменяются при каждом poll, snapshot/reaction suppression почти не помогает; current-state updates и global rebuild добавляют WAL и bloat.

## 5. Endpoint/query performance

| Endpoint/page | Relations/projections | SQL/request на miss | Доступное измерение | Cold/warm p50/p95/p99 |
|---|---|---:|---|---|
| Overview 3h/1d/7d/30d, 50/200 | legacy overview, account/latest projections | ~3 | Single plan: 50 — 7.38 ms; 200 — 3.67 ms | NOT PROVEN |
| Institution detail | institution period, account latest, publication lists | от ~5 до 2 + 2N + pages | Нет final-schema load evidence | NOT PROVEN |
| Account detail/list | account latest, publication/history | ~4–5, frontend получает все pages | Нет | NOT PROVEN |
| Publication detail/history | catalog, publication_history | ~6 и до 101 HTTP pages | Нет; есть correctness defect | NOT PROVEN |
| Comparison candidates | cohorts/members | ~3 + continuation | Нет для всех платформ | NOT PROVEN |
| Comparison series | comparison hourly | ~4 + continuation | Старый VK single plan 33.92 ms | NOT PROVEN |
| Rating | account/latest, publication/latest | ~4 | Старые single plans 1.26–4.19 ms | NOT PROVEN |
| Legacy redirects | identity/catalog | ~3 | Старый aggregate p95 19.97 ms | p50/p99 NOT PROVEN |
| Aggregate cached public HTTP | Caffeine/Redis | 1 revision SQL даже на hit | Старый synthetic p95: hit 23.70 ms, miss 44.28 ms | Не final schema |

Существующие public-read-v29-final-r2 и query-plan evidence имеют productionAcceptance=false. Они не покрывают cold reads, все periods, MAX, history более 1000 points, temp spill и realistic concurrency.

Каждый cache hit выполняет revision SQL, который cross-join-ит всю dataset_revision с шестью projection names, группирует и сортирует revisions. Его цена потенциально растёт со всей revision history.

Предварительные SLO — public HTTP p95 не более 500 ms, ordinary SQL p95 не более 200 ms, first uncached graph не более 1 s, cached p95 не более 100 ms — остаются разумными, но не подтверждёнными.

## 6. Redis decision matrix

| Endpoint | PostgreSQL | Caffeine L1 | Redis L2 | Projection/rollup |
|---|---|---|---|---|
| Overview | должен отвечать самостоятельно | да | да, bounded keys | incremental institution/account period |
| Institution detail | да | да | допустим | incremental institution period/latest |
| Account detail | да | да | допустим | account latest + bounded publication page |
| Publication detail | да | короткий | только компактная карточка | publication latest |
| Publication history | bounded SQL обязателен | ограниченно | не кешировать полный большой payload | raw + hourly/daily |
| Comparison candidates | да | да | да | cohort/member |
| Comparison series | fallback не более 1 s | да | да для популярных параметров | incremental hourly |
| Rating | да | да | да | account/publication latest |
| Pagination cursors | да | обычно нет | обычно нет | index-seek pagination |
| Legacy redirects | да | допустим | не нужен | identity |
| CSV/export | streaming PG/archive | нет | нет | export/archive facts |

Unit tests подтверждают Redis fail-open, revision/build cache keys, SHA-256 hiding of query values и ETag/304. TTL: Caffeine 2 минуты, Redis 10 минут.

Не доказаны hit ratio, key cardinality, value sizes, memory pressure, Redis outage под нагрузкой и stale window. Single-flight/stampede protection отсутствует. Redis Compose не задаёт maxmemory/eviction policy при cgroup 80 MiB.

## 7. Publisher failure matrix и peak disk

Пустой rebuild после ручного disposable retention seed:

- duration 1.17 s;
- database 31,266,495 → 31,307,455 bytes, delta 40,960;
- WAL delta 128,680 bytes;
- temp 0;
- source_bytes 9,912,320;
- required_bytes 5,398,446,080;
- available_bytes 6,353,297,408.

Это пустая БД, а не production evidence.

| Сценарий | Результат |
|---|---|
| Явный manual start | PASS по script/systemd |
| Type=oneshot, Restart=no | PASS |
| Не вызывается deploy/targets/collectors | PASS по dependency graph |
| Два concurrent runs | PASS: второй exit 75 по flock |
| Повтор той же revision | PASS: already ready, WAL +56 bytes |
| Обычная нехватка места | PASS fail-closed, предыдущая ready revision сохранена |
| Arithmetic overflow | **FAIL**, отрицательный required_bytes разрешает rebuild |
| Неверный schema contract | PASS fail-closed, exit 65 |
| Missing retention policy | Fail-closed, но fresh deployment остаётся без ready generation |
| Ошибка publisher | Pending request остаётся; automatic retry loop отсутствует |
| Новая revision во время rebuild | High-water/coalescing подтверждены кодом; runtime NOT PROVEN |
| Locks/blocked collector transaction | NOT PROVEN |
| Kill/crash in the middle | NOT PROVEN |
| PostgreSQL restart | NOT PROVEN |
| Redis outage | Publisher не использует Redis; post-publish invalidation recovery NOT PROVEN |
| Peak disk на 5–6 GiB source | NOT PROVEN |

Фактический rebuild остаётся global. Он создаёт TEMP usable snapshot с двумя indexes и выполняет DELETE/INSERT для publication latest/hourly/daily/monthly/period, comparison cohorts/members/hourly, institution period, legacy overview/account и account latest. Шесть readiness names не равны шести физическим tables.

Реальный peak:

    old serving MVCC versions
    + new serving heap and indexes
    + TEMP usable snapshot and two indexes
    + WAL
    + possible temp spills
    + raw/history relations
    + filesystem reserve

Guard использует source_bytes × 3 + 5 GiB. При source около 5.5 GiB он запросил бы около 21.5 GiB и при 17 GiB free, вероятно, отказал бы. Но source set и multiplier не откалиброваны, а overflow уже доказал fail-open.

| Вариант | Correctness | Peak disk | Query latency | Complexity | Rollback |
|---|---|---|---|---|---|
| Current bounded global oneshot | consistent MVCC snapshot | высокий, не измерен | readers стабильны, rebuild длинный | низкая | нет явной generation retention |
| Incremental dirty-set/high-water | достижима с versioned rows/publish fence | O(batch/dirty set) | предсказуемая | средняя/высокая | предыдущая published revision сохраняется |
| Raw/hourly/daily без части serving | хорошо для bounded history | низкий | плохо для global overview/rating без rollup | средняя | простой |

Рекомендация: incremental dirty-set для overview/rating/comparison и indexed raw/hourly/daily для bounded publication/account history.

## 8. Подтверждённые defects P0–P3

| Priority | Defect | Воспроизведение/доказательство |
|---|---|---|
| P0 | Fresh final schema не публикуется | final-schema bootstrap → revision/request → publisher --once → exit 75 по missing retention |
| P0 | Stale publication_history может маркироваться текущей revision | normal publisher обновляет шесть states; detail SQL читает history без revision predicate |
| P0 | Cutover требует удалённую V1–V31 Flyway chain | preflight hard-code-ит version/count/hash и exact rows |
| P1 | Capacity overflow fail-open | multiplier max signed integer → negative required_bytes → rebuild accepted |
| P1 | Institution N+1/all-publications load | sequential account detail и full continuation до slice 500 |
| P1 | history_limit не ограничивает backend work | publication page вызывает loadPublicationHistory без limit |
| P1 | 2 GiB multiline-service overcommit | PG512 + Redis80 + API около 1.4 GiB + unbounded web/collectors |
| P2 | Revision lookup зависит от всей history | dataset_revision CROSS JOIN six projections ORDER BY revision |
| P2 | Redis не имеет bounded eviction | cgroup 80 MiB, maxmemory/policy отсутствуют |
| P2 | Schema smoke противоречит final schema | smoke.sql требует flyway/migration schemas |
| P2 | DB-dependent Python tests не синхронизированы | 53 passed, 57 failed, 10 errors на disposable PG; failures включают old Flyway/projection contracts |
| P3 | Wide repeated fingerprints/evidence/reaction keys | optimization opportunity; exact saving требует production-shaped benchmark |

## 9. Реализовано правильно и доказано

- Publisher отсутствует в deploy targets, имеет oneshot, Restart=no, flock и не содержит retry/sleep loop.
- Collectors не зависят от publisher в systemd dependency graph.
- API/web deploy restart-ит API, web и outbox, но не publisher/collectors.
- Compose base и local/production-small overlays проходят docker compose config.
- PostgreSQL/Redis используют named persistent volumes.
- final-schema.sql загружается на чистый PostgreSQL 18.6.
- Semantic suppression и transaction idempotency частично доказаны реальным PostgreSQL integration test.
- Cache fail-open, revision keys и ETag доказаны unit tests.
- Frontend production build, lint, TypeScript, OpenAPI check, 100 unit tests и 64 Playwright tests прошли.
- Rollback ordering статически защищает database writers.
- Existing DR rehearsal выполнял physical backup/restore/PITR на локальной БД около 3.95 GB: standby RTO 5.55 s, full restore 16.42 s, PITR 16.53 s, marker gap 0.315 s. Evidence имеет productionAcceptance=false.

## 10. Заявлено кодом, но не доказано production-shaped measurement

- снижение growth не менее 70% и не более 0.35 GiB/day;
- heap/index/TOAST/WAL bytes per iteration;
- HOT ratio и autovacuum sustainability;
- publication heartbeat и concurrent collector deduplication;
- все page/graph SLO без Redis;
- partition pruning на всех платформах и periods;
- отсутствие temp spill/checkpoint pressure;
- publisher peak disk, lock footprint и crash recovery;
- data-bearing transition production database;
- Redis cardinality/eviction/stampede;
- reboot/start ordering;
- production backup RPO/RTO;
- total memory safety на 2 GiB host.

## 11. Рекомендуемая target architecture

1. PostgreSQL остаётся source of truth; Redis остаётся disposable accelerator.
2. Raw semantic snapshot сохраняется только при изменении плюс 24h heartbeat.
3. Availability делится на one-row current state и immutable transition events.
4. Raw history хранится 70–90 дней, hourly покрывает полный interactive horizon, daily хранится long-term.
5. Cold archive — immutable partition exports с checksum/manifest и доказанным restore.
6. Dirty publications/accounts/institutions/time buckets фиксируются по revision.
7. Publisher обрабатывает bounded batches и пишет versioned projection rows с validity interval.
8. Published high-water переключается только после завершения всего dirty set; незавершённая revision невидима API.
9. Предыдущая published revision сохраняется для rollback и удаляется небольшими GC batches.
10. Current revision читается из singleton/fenced state без scan всей dataset_revision.
11. Redis получает maxmemory, явную eviction policy, bounded key classes, single-flight и hit/miss/store-failure metrics.
12. Publication history принимает period/limit в SQL; institution/account используют bounded aggregate/page endpoints.

## 12. Поэтапный план исправлений

1. Исправить P0 publication_history/revision correctness.
2. Добавить явный idempotent operational seed/release step для retention policy и test clean install → first publish.
3. Удалить Flyway V31 requirements из final cutover gate либо формально отделить legacy transition evidence от runtime schema contract.
4. Переписать capacity arithmetic на checked numeric calculation с upper bounds и fail-closed overflow.
5. Убрать frontend all-pages/N+1; ввести bounded server-side endpoints.
6. Ввести systemd memory/CPU limits и свести total budget для 2 GiB.
7. Реализовать dirty-set/versioned incremental publisher.
8. После restored-copy benchmark оптимизировать fingerprints/evidence/reactions и indexes.
9. Настроить Redis maxmemory/eviction и single-flight.
10. Выполнить production-shaped storage/performance/failure rehearsal.

## 13. Production deployment gate

Перед rollout обязательны:

1. Restore последнего production backup в disposable PostgreSQL 18.6.
2. Data-bearing rehearsal transition-production-to-final.sql, повторный run и rollback rehearsal.
3. 24–48 часов replay/работы всех четырёх collectors с per-iteration measurements.
4. Подтвердить growth не более 0.35 GiB/day, снижение не менее 70%, bounded WAL/temp/checkpoints и preservation corrections/deletion/recovery semantics.
5. Снять EXPLAIN ANALYZE BUFFERS SETTINGS JSON для всех query patterns на restored copy.
6. Измерить cold/warm p50/p95/p99 при realistic concurrency и Redis disabled.
7. Выполнить publisher failure rehearsal в quota, соответствующей 17 GiB free и 2 GiB RAM: kill, PG restart, no-space, new revisions, two instances, collector writes.
8. Проверить production backup restore и утвердить RPO/RTO.
9. Проверить reboot ordering и memory pressure.
10. Затем deploy API/web/outbox shadow без publisher, проверить readiness/cache fail-open, отдельно запустить publisher вручную, постепенно переключать Nginx routes. Collectors не останавливать; rollback web/API выполнять независимо от writers.

## 14. Component and test matrix

| Проверка/команда | Результат | Среда/ограничение |
|---|---|---|
| rtk .venv/bin/python -m pytest -q | 530 passed, 167 skipped | Unit/local; PG skips не считаются integration success |
| publisher lifecycle и operational static gates | 64 passed | Static assertions |
| Focused collector PostgreSQL idempotency test | 2 passed | Disposable PostgreSQL 18.6 |
| Broad DB-dependent Python selection | 53 passed, 57 failed, 10 errors | Disposable final-schema DB; old Flyway/projection contracts |
| rtk mvn -q -f backend/pom.xml test | 171 passed, 48 skipped, 0 failed | Spring unit; external DB/Redis portions skipped |
| Frontend lint/typecheck/OpenAPI/unit | PASS; 100 tests | Node 24 disposable build image |
| Frontend Playwright | 64 passed | Disposable container with Chromium |
| Frontend production build | PASS | Next.js 16.3.3, Node 24 |
| Frontend bundle gate | PASS | Все bundles уложились в configured budget |
| final-schema clean bootstrap | PASS SQL; FAIL operational completeness | Empty disposable PG; retention seed absent |
| migration/schema/smoke.sql on final schema | FAIL | Requires obsolete flyway/migration schemas |
| transition rehearsal | BLOCKED | Нет source-shaped data-bearing production copy |
| postgres-storage-audit.sql | PASS execution, NOT PROVEN result | Empty final-schema database |
| Current query-plan acceptance | BLOCKED | Only old synthetic productionAcceptance=false evidence |
| Publisher empty rebuild | PASS after manual disposable retention seed | 1.17 s, +40,960 DB bytes, +128,680 WAL bytes |
| Publisher production-shaped disk/lock failure suite | BLOCKED | Production-shaped copy unavailable |
| Cache/Redis correctness | PARTIAL PASS | Unit fail-open/key/ETag; no Redis load/capacity test |
| Backup/restore | PARTIAL PASS | Real local 3.95 GB rehearsal; productionAcceptance=false |
| Compose validation | PASS | Base+local and base+production-small |
| systemd publisher isolation | PASS static | Reboot/runtime pressure not tested |
| 2 GiB resource readiness | FAIL | Aggregate budget not bounded |
| Production deploy readiness | **NO-GO** | P0/P1 gates remain |

## Environment and cleanup

- Docker client/server 29.2.1, Docker Desktop 4.64.0.
- PostgreSQL disposable runtime 18.6.
- Redis 8.10.0 is pinned in Compose; no existing local Redis runtime was available to verify.
- Java 21, Maven 3.9.11.
- Python 3.13.5, pytest 8.4.1, psycopg 3.3.5.
- Host Node 20.6 was unusable due missing ICU; Node 24 and pnpm 11.19.0 were verified in disposable Docker builds.
- Initial local state: zero containers, zero volumes, one image; host free space approximately 520 GiB.
- Final state: zero containers. The disposable PostgreSQL container was removed.
- One zero-byte anonymous Docker volume created during the audit remains because deletion was rejected by the safety policy. Disposable frontend image tags были автоматически очищены; остался только build cache.
- Final host free space: approximately 514 GiB.
- Final git branch, commit, divergence and pre-existing working-tree changes match the recorded baseline; this report is the only intentional new workspace file.
