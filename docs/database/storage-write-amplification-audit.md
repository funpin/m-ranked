# Аудит storage/write amplification PostgreSQL

Дата аудита: 2026-09-08. Область: `publication_metric_snapshot`,
`deletion_observation`, `reaction_breakdown` и непосредственно связанные пути
коллектора/аналитики. Производственная БД не изменялась.

## Статус доказательств

- **Измерено в предоставленном schema-export:** PostgreSQL 18.6, capture
  `2026-09-07T19:23:15Z`, 5 532 546 751 bytes (5,15 GiB), из них
  2 580 602 880 bytes (2,40 GiB) физических индексов.
- **Подтверждено кодом/DDL:** пути записи, ограничения, формы ключей, запросы
  чтения, schema bootstrap/partitioning и семантика коррекций.
- **Проверено локальными тестами:** нормализация, replay, change detection,
  heartbeat, эксплуатационные манифесты. PostgreSQL-интеграционные тесты в этом
  окружении не запущены: DSN и пригодный локальный PostgreSQL отсутствуют;
  попытка получить disposable Docker-окружение остановилась на загрузке образов
  до создания контейнеров.
- **Не измерено:** `pg_stat_*`, `pg_stat_statements`, WAL, реальные ширины
  строк/ключей, before/after планы и latency. Для этого добавлен read-only
  скрипт `operations/sql/postgres-storage-audit.sql`.

## 1. Физическая картина до изменения

| Семейство | Всего | Heap | Индексы | Статус источника |
| --- | ---: | ---: | ---: | --- |
| Вся БД | ~5,15 GiB | — | ~2,40 GiB (46,6%) | предоставленное измерение |
| `publication_metric_snapshot`, 63 partitions, planner ~4,84 млн rows | 4 001 021 952 B (3,73 GiB) | 2 091 294 720 B | 1 904 058 368 B (1,77 GiB) | schema-export |
| partition `2026_08`, planner ~2,16 млн rows | 1 917 452 288 B | 1 007 337 472 B | ~910 MB | schema-export |
| `deletion_observation`, planner 1 221 373 rows | 336 420 864 B | 143 556 608 B | 192 847 872 B в трёх индексах | schema-export |
| `reaction_breakdown`, 63 partitions, planner ~10,07 млн rows | 1 095 909 376 B (1,02 GiB) | 640 843 776 B | 454 172 672 B | schema-export |
| `reaction_breakdown_2026_09` | ~646 MiB | ~376 MiB | PK ~270 MiB | предоставленное измерение |

63 snapshot partitions создают ровно 441 child indexes (63 × 7), а 63 reaction
partitions — 63 child PK. Поэтому большое число объектов
`pg_class` само по себе не является over-indexing; сравнивать нужно физические
байты, планы и write cost.

## 2. Логические индексы и решения

| Индекс | Класс/назначение | Решение |
| --- | --- | --- |
| snapshot PK `(published_month,id)` | PK, цель composite FK reaction | оставить |
| snapshot UQ `(month,publication,bucket,source_fingerprint)` | exact replay и запрет переиспользования fingerprint | оставить |
| snapshot UQ `(month,publication,bucket,correction_sequence)` | порядок immutable corrections/active view | оставить |
| snapshot `(publication_id,observed_at DESC,id DESC)` | latest/history reads; collector теперь добавляет `published_month` для partition pruning | оставить |
| snapshot `(collection_run_id,publication_id)` | lineage/run/archive access | оставить до получения runtime usage/plans |
| BRIN `observed_at`, `collected_at` | дешёвые time-series paths, около 40 KiB/child в примере | оставить |
| reaction PK `(month,snapshot_id,reaction_key)` | FK-owned map rows и uniqueness | оставить |
| legacy deletion PK `(id)` | legacy history/порядок; внешних FK/прикладных ссылок не найдено | не трогать в production transition |
| legacy deletion UQ `(publication_id,collection_run_id,observed_at)` | replay старого writer | оставить для rollback compatibility |
| legacy deletion `(publication_id,observed_at DESC)` | latest legacy probe | оставить до завершения compatibility/cleanup |
| availability-state PK `(publication_id)` | одна текущая строка и сериализация update | новый, необходим |
| availability-event PK `(publication_id,collection_run_id,observed_at)` | event idempotency | новый, необходим |

Отдельный time-order индекс для availability events намеренно не добавлен:
прикладного запроса на историю пока нет. Он должен появиться только вместе с
реальным consumer и подтверждённым планом.

## 3. Причины amplification

1. **No-op availability history — главный подтверждённый источник.**
   `persist_account_batch()` автоматически строил `present` probe для каждой
   несинтетической публикации и `_persist_deletion_probe()` всегда добавлял
   `deletion_observation`. Это соответствует предоставленным 2,46 млн строк/день,
   99,99% `present` и примерно 0,67 GB/день постоянного роста.
2. **Poll и historical state были сцеплены.** Нормализатор включает
   `scheduled_at`, `observed_at`, `collected_at` и `sampling_bucket` в полный
   `source_fingerprint`; поэтому успешный новый poll всегда имел новый digest,
   даже если исторически значимые метрики/качество/evidence/reactions не менялись.
3. **Широкие constraint-backed B-tree.** `source_fingerprint` от native
   collector — SHA-256 hex длиной 64 символа. Он входит в один из двух важных
   UNIQUE. Это реальная ширина ключа, но индекс нельзя убрать: V9 trigger и тесты
   используют его для exact replay/correction invariant.
4. **Reaction rows физически широки, но не over-indexed.** Единственный PK
   повторяет `reaction_key TEXT`. Найденные consumers собирают полный map для
   projection, archive, reverse sync и legacy export; глобальных фильтров по
   типу реакции не найдено. Packed JSONB выглядит правдоподобным кандидатом, но
   без storage/read benchmark менять модель рискованно.
5. **`metric_evidence` не пустой sparse JSONB в native write path.** Коллектор
   всегда создаёт объект для четырёх метрик с quality/source/flags. Вертикальное
   разделение может экономить heap, но его цена и выигрыш не измерены.

## 4. Проверка гипотез

| Гипотеза | Вывод |
| --- | --- |
| H1 no-op `present` доминирует в deletion growth | подтверждена кодом + предоставленным измерением |
| H2 много неизменных snapshots можно пропускать | подтверждена предоставленными 55% + отсутствием change detection в старом коде |
| H3 wide UNIQUE дороги, но сохраняют invariants | подтверждена; не изменены |
| H4 fingerprint TEXT увеличивает ключ | формат hex-64 подтверждён кодом; DB width/экономия требуют staging |
| H5 reaction TEXT увеличивает PK | физически правдоподобно; cardinality/экономия не измерены |
| H6 raw index count в основном partition multiplication | подтверждена DDL |
| H7 мелкие overlap indexes вторичны | новых кандидатов с достаточным доказательством нет |
| H8 evidence раздувает hot row | объект всегда присутствует; байты/выигрыш не измерены |

## 5. Ранжирование изменений

| Кандидат | Рост/запись | Риск | Решение |
| --- | --- | --- | --- |
| Current state + meaningful availability events | максимальный, устраняет известные ~0,67 GB/day no-op history | средний | реализовано в финальном контракте |
| Semantic snapshot suppression + 24h heartbeat | высокий; верхняя оценка — до 55% snapshot/reaction writes вне heartbeat | средний | реализовано консервативно |
| Binary source digest в UNIQUE | потенциально высокий index saving | высокий online migration/compatibility | отложено до DB width + plan benchmark |
| Packed reaction map или dictionary ID | потенциально высокий | высокий, затрагивает archive/projections/reverse sync | отложено до benchmark |
| Vertical evidence table | неизвестный | средний/высокий | отложено |
| Drop indexes по `idx_scan=0` | неизвестный | высокий | не выполнялось |

## 6. Целевая финальная модель

`publication_availability_state` хранит одну строку на публикацию: authoritative
status, последний probe, `last_checked_at`, `last_present_at`,
`first_missing_at`, счётчик missing, reason и последний run. Fillfactor 80
оставляет место для HOT updates; индексируемый PK не меняется.

`publication_availability_event` получает строку только при первом состоянии,
status transition, изменении probe outcome/reason или продвижении missing к
confirmation. Повторный обычный `present` лишь продвигает current state.
Traceability успешного poll сохраняется в `collection_run` и
`collection_account_result`; последний per-publication run остаётся в state.

Snapshot получает nullable `semantic_fingerprint BYTEA(32)`. Новые rows
хешируют versioned projection из counters, per-metric quality, evidence/source,
reaction map, uncertainty, synthetic/history/source semantics, исключая времена
опроса и sampling bucket. Совпадающее состояние не записывается до
`PUBLICATION_SNAPSHOT_HEARTBEAT_HOURS` (24 по умолчанию). Изменение любого
включённого факта или correction state сохраняет полную immutable запись.

## 7. Миграция, cutover и rollback

Одноразовый production transition выполняет metadata-only добавление nullable BYTEA, создаёт две небольшие
неpartitioned таблицы и backfill текущего availability state чтением legacy
history. Старые rows не переписываются и не удаляются; cleanup — отдельная
будущая операция. INSERT grant старого writer сохраняется на rollback window.

Порядок rollout:

1. На staging запустить diagnostic script и зафиксировать baseline.
2. Применить `transition-production-to-final.sql`; проверить SHA-256, duration, locks и финальный schema contract.
3. Дождаться завершения старых collector batches и переключить collectors на финальный contract.
4. Проверить row rates: state updates, event inserts, skipped/full snapshots,
   WAL, autovacuum/HOT ratio и projection correctness.
5. После rollback window отдельно решить revocation legacy INSERT и retention.

Rollback приложения: вернуть предыдущий collector; legacy INSERT permission
сохранён. Финальная additive-схема остаётся единственным поддерживаемым contract.
Не удалять финальные tables/column и не чистить legacy history в аварийном rollback.
После transition новый collector продолжает обновлять `publication.deleted_at`, поэтому
public API остаётся совместимым.

## 8. Ожидаемый эффект и границы утверждений

- **Рассчитано из предоставленных данных:** постоянный рост legacy availability
  history должен уменьшиться приблизительно на 0,67 GB/day минус редкие
  transition events. Current-state heap не растёт по числу polls, но создаёт WAL
  и dead tuples; фактический эффект зависит от HOT/autovacuum.
- **Выведено из 55% unchanged:** вне heartbeat может быть устранено до 55%
  snapshot heap writes, всех соответствующих B-tree entries и reaction rows.
  Это не измеренный GB/day результат.
- **Не доказано:** достижение общего 0,35–0,45 GB/day. Для расчёта нужны реальные
  rows/run, WAL и bytes/row после transition. Цель нельзя объявлять достигнутой до
  staging/production-like замера.

## 9. Обязательный after-measurement

Запустить от read-only роли:

```bash
rtk psql "$AUDIT_DATABASE_URL" -X -f operations/sql/postgres-storage-audit.sql
```

На staging дополнительно выполнить `ANALYZE`, затем сохранить
`EXPLAIN (ANALYZE, BUFFERS, WAL, SETTINGS)` для latest-publication lookup,
snapshot insert/change/heartbeat, availability update/transition, history
projection и reaction aggregation. Production `EXPLAIN ANALYZE` не выполнять,
если запрос может заметно нагрузить систему.

## 10. P4 usage matrix и lifecycle-кандидаты

Это анализ, не политика удаления. Исходный код подтверждает потребителей и
форму запросов, но не подтверждает допустимый срок хранения.

| Таблица/поле | Кто читает | Диапазон/детализация | Допустимый retention сейчас |
| --- | --- | --- | --- |
| `publication_metric_snapshot`: counters, quality, evidence, timestamps | serving rebuildы, detail/history API, archive/reconciliation | latest плюс полный chronological history по publication; исходная точность | не определён продуктом; не удалять |
| `reaction_breakdown`: key/count | history/reaction deltas, archive/reconciliation, recovery CSV tooling | все keys для каждой сохранённой snapshot | следует retention родительской snapshot; не удалять отдельно |
| `account_metric_snapshot`: subscribers/display/quality | overview/activity projections, bridge recovery tests | latest и period-first/period activity | не определён; period-first запрещает бездоказательное thinning |
| `publication_availability_state` | collector deletion state machine | одна current row/publication | пока существует publication |
| `publication_availability_event` | audit/recovery | только meaningful transitions | audit-policy отсутствует; не удалять |
| legacy `deletion_observation` | rollback bridge/tests, старые reconciliation paths | chronological evidence | сохранить через rollback/recovery window; дата вывода требует approval |
| serving analytics tables | API/readiness | одна активная mutable generation | держать текущую generation; rebuild уже заменяет её атомарно |
| `publication_history`/`publication_content` | detail API | полный доступный history/content, independent watermark | не включать в hot rebuild; retention не назначен |
| `legacy_export_row` | legacy CSV compatibility | полный экспорт на explicit bootstrap | контракт endpoint должен быть подтверждён до retirement |
| `raw_payload` и archive manifest | recovery/audit tooling | source evidence по принятой archive policy | существующий purge остаётся выключен |

Трёхуровневая целевая модель для измерения на production-shaped copy:

1. Raw high-frequency: полная snapshot/reaction детализация за ограниченное
   окно (кандидаты 30/60/90 дней сравнить, срок пока **не выбран**).
2. Medium-term hourly: существующие `publication_hourly` и агрегаты качества;
   проверить, достаточно ли их для UI/detail и period semantics до thinning.
3. Long-term daily: daily/monthly/period rollups плюс immutable recovery archive;
   проверить legacy export, corrections и audit before accepting loss of raw.

Partitioning уже помогает pruning и потенциальному будущему detach/drop, но не
уменьшает число вставок. BRIN временных колонок мал и сохраняется. Удалять
B-tree по одному `idx_scan=0` нельзя: сначала нужен полный business cycle,
query plans и write benchmark. Packed JSONB reaction map, бинарный digest,
TOAST/compression и vertical evidence остаются benchmark-кандидатами.

Любой будущий retention требует: продуктовый владелец и юридический/audit срок,
проверенный cold export + restore, сравнение API/UI до/после, WAL/temp/latency,
и отдельное operational window. Освобождение места файловой системе после
логического удаления не обещается: rewrite/`pg_repack`/новый tablespace —
отдельное capacity-reviewed изменение.
