# ADR-004: Многоуровневая политика хранения данных

- Status: **Proposed**
- Date: 2026-09-02
- Owners: product / data / operations
- Related: [data lifecycle](../views/data-lifecycle.mmd),
  [replication and backup](../views/replication-backup.puml)

## Context

Накопленная SQLite выросла примерно до 250 MB чуть более чем за месяц. На
primary-сервере запланировано 30 GB диска. Текущая очистка архивирует только
legacy Telegram posts и вызывается только одним режимом Telegram collector;
generic VK/MAX/Rutube snapshots и часть Telegram-путей растут без retention.

Проекту одновременно нужны:

- детальные недавние графики;
- долгосрочные исследования и воспроизводимые рейтинги;
- возможность доказать происхождение результата;
- ограничение hot database, WAL, backup и raw payload;
- восстановление после аварии.

Backup retention не должен подменять product data retention, а replica не
является backup.

## Decision

Применить tiered retention ко всем платформам по типу данных, а не по collector.

| Data class | Hot PostgreSQL | Cold archive | Итоговое правило |
|---|---:|---:|---|
| Raw upstream payload/body | 7 дней | Нет по умолчанию | Purge; сохраняются hash, source fields и lineage |
| Full-resolution publication snapshots | минимум 40 дней | 3 года | Monthly partition экспортируется в Parquet+Zstd перед DROP |
| Full-resolution account/subscriber snapshots | 40 дней | 3 года | После hot периода сохраняется daily series/архив |
| Publication/account identity и metadata | Пока сущность существует + история изменений | Не требуется | Не удалять вместе со snapshot partition |
| Daily/weekly aggregates и cohort coverage | Бессрочно | Optional copy | Малый объем, нужен для долговременного анализа |
| Formula definitions, rating runs/components | Бессрочно | Backup | Published versions immutable |
| Official rating observations и source hash | Бессрочно | Backup | История не перезаписывается |
| Anomaly signals и reviews | 3 года минимум | Backup | Терминология и evidence сохраняются вместе |
| Admin audit log | 3 года минимум | Backup | Secrets/raw tokens запрещены |
| Collection run details | 180 дней | Aggregate бессрочно | Sanitized error code; verbose logs короче |
| Application logs | 30 дней | Нет по умолчанию | Security events — по отдельной policy |

Snapshots партиционированы по календарному месяцу `published_at`, поэтому
«40 дней» означает минимум 40 дней наблюдения публикации: partition удаляется
только после завершения tracking всех публикаций этого месяца. Фактическое hot
окно поэтому может быть длиннее примерно на один месяц. Если capacity forecast
покажет проблему, допускаются weekly partitions без изменения семантики
retention.

Перед удалением hot partition обязательно:

1. сформировать Parquet+Zstandard с versioned schema;
2. записать диапазон, row count, min/max timestamp и SHA-256;
3. прочитать sample и сверить count/checksum;
4. атомарно опубликовать `archive_manifest`;
5. только затем выполнить `DROP PARTITION`;
6. при любой ошибке остановить purge и уведомить оператора.

Cold archive хранится на втором сервере в отдельной failure domain. Удаление
объекта после трех лет требует сначала подтвердить, что необходимые aggregates,
rating inputs и lineage уже сохранены. Продление срока — product decision без
изменения hot schema.

## Backup policy

Начальная политика, уточняемая после измерения размера/WAL:

- непрерывный WAL archive с целевым RPO не более 15 минут;
- daily base backup — 14 точек;
- weekly — 8 точек;
- monthly — 12 точек;
- шифрованная копия как минимум одной линии backup вне primary;
- daily автоматическая проверка выбранного backup;
- quarterly полный restore/PITR drill с отчетом времени.

Platform session files и secrets не попадают в аналитический cold archive. Их
backup шифруется отдельно, имеет отдельный ключ и процедуру ротации.

## Capacity controls

- Размер таблиц, индексов, partitions, WAL, Redis и archive spool измеряется.
- Forecast строится для текущего числа accounts и сценариев 5x/10x.
- Alert при 70% диска, critical при 85%.
- Maintenance не начинает export, если staging+WAL не помещаются с резервом.
- Raw payload never участвует в обычных dashboard queries.
- Retention job idempotent и единственный для всех платформ.

## Consequences

Положительные:

- hot database имеет ограниченный рост;
- долгосрочные исследования сохраняют компактные агрегаты и cold details;
- удаление целой partition дешевле массового `DELETE`;
- одинаковая policy закрывает текущий разрыв между платформами.

Отрицательные:

- cold запросы медленнее и не обслуживают обычный UI;
- Parquet schema evolution и restore требуют тестов;
- фактическое hot окно зависит от размера partition;
- 3-летний архив занимает место на DR и требует lifecycle monitoring.

## Alternatives considered

### Хранить все snapshots в PostgreSQL бессрочно

Отклонено для 30 GB primary: indexes, WAL и backup будут расти вместе с данными.

### Оставить отдельные CSV.GZ на каждый Telegram post

Отклонено: создает много мелких файлов, не покрывает другие сети и неудобно для
schema evolution/аналитического чтения.

### Удалять все детали после 40 дней без cold archive

Отклонено: делает невозможной проверку долгосрочной динамики и повторный расчет
новой методики по старым данным.

## Fitness functions

- Retention integration test создает данные всех четырех платформ и подтверждает
  одинаковую обработку cutoff.
- Purge невозможен без verified manifest.
- Aggregate/rating results остаются воспроизводимыми после DROP hot partition.
- Restore drill укладывается в принятые RPO/RTO.
- Capacity report еженедельно прогнозирует дату достижения 70% диска.

## Revisit when

- появляется юридически утвержденный срок;
- cold storage или disk budget меняется;
- пользователи регулярно запрашивают полные данные старше 40 дней;
- восстановление по Parquet не укладывается в исследовательские требования.
