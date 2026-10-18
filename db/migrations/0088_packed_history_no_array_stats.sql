-- 0088 — ANALYZE упакованной истории не распаковывает массивы.
--
-- ingest.publication_metric_history (0059) держит ряд поста в двадцати
-- массивах, и почти весь объём — TOAST (toast_tuple_target = 128): на проде
-- 18.10 куча 50 МБ, TOAST 1,09 ГБ на 75 тыс. строк. ANALYZE берёт до 30 тыс.
-- строк и для статистики каждого массива достаёт и распаковывает значение
-- целиком. 18.10 автоанализ шёл 614 с, прочитал 1,04 млн блоков и пришёлся на
-- пик перегрузки Сервера 2; в среднем 58 прогонов — по 128 с.
--
-- Статистика этих столбцов планировщику не нужна: запросы фильтруют таблицу
-- по publication_id, published_month, first/last_observed_at и late_rows, а
-- массивы только разворачивают внутри LATERAL. Сравнение планов читателей на
-- копии прода (выдача истории, отпечаток, SERIES/PROGRESS анализа, сводка
-- карточек) — в описании изменения. ANALYZE на копии: 13–16 с → 0,1 с.
--
-- Блокировка — SHARE UPDATE EXCLUSIVE на мгновение; с идущим автоанализом
-- она конфликтует, поэтому lock_timeout. Прежние строки pg_statistic этих
-- столбцов ANALYZE не удаляет, а лишь перестаёт обновлять; планы с ними и без
-- них совпадают. На проде 18.10 после миграции ANALYZE — 3,4 с.
--
-- Откат: те же ALTER COLUMN … SET STATISTICS -1.
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE ingest.publication_metric_history
    ALTER COLUMN snapshot_id SET STATISTICS 0,
    ALTER COLUMN observed_at SET STATISTICS 0,
    ALTER COLUMN collected_lag SET STATISTICS 0,
    ALTER COLUMN created_lag SET STATISTICS 0,
    ALTER COLUMN age_residual SET STATISTICS 0,
    ALTER COLUMN bucket_residual SET STATISTICS 0,
    ALTER COLUMN run_seq SET STATISTICS 0,
    ALTER COLUMN views_count SET STATISTICS 0,
    ALTER COLUMN reactions_count SET STATISTICS 0,
    ALTER COLUMN comments_count SET STATISTICS 0,
    ALTER COLUMN shares_count SET STATISTICS 0,
    ALTER COLUMN codes SET STATISTICS 0,
    ALTER COLUMN correction_sequence SET STATISTICS 0,
    ALTER COLUMN supersedes_snapshot_id SET STATISTICS 0,
    ALTER COLUMN correction_reason SET STATISTICS 0,
    ALTER COLUMN semantics_version SET STATISTICS 0,
    ALTER COLUMN capability_version SET STATISTICS 0,
    ALTER COLUMN evidence_id SET STATISTICS 0,
    ALTER COLUMN reaction_ref SET STATISTICS 0,
    ALTER COLUMN reaction_dict SET STATISTICS 0,
    ALTER COLUMN block_sha256 SET STATISTICS 0;

COMMIT;
