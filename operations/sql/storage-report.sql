-- Отчёт о хранении и скорости для решений по оптимизации. Только чтение:
-- транзакция READ ONLY, короткие таймауты, выборки ограничены. Без адресов,
-- паролей и содержимого строк — только размеры, счётчики и тексты запросов.
\set ON_ERROR_STOP on
\pset pager off
\pset footer off

BEGIN TRANSACTION READ ONLY;
SET LOCAL statement_timeout = '90s';
SET LOCAL lock_timeout = '1s';

\echo '## База'
SELECT pg_size_pretty(pg_database_size(current_database())) AS database,
       current_setting('server_version') AS version,
       (SELECT stats_reset FROM pg_stat_database WHERE datname = current_database()) AS stats_reset;

\echo '## Настройки, влияющие на место и скорость'
SELECT name, setting, unit FROM pg_settings
WHERE name IN ('shared_buffers', 'effective_cache_size', 'work_mem', 'maintenance_work_mem',
               'random_page_cost', 'jit', 'max_parallel_workers_per_gather', 'default_toast_compression',
               'wal_compression', 'checkpoint_timeout', 'max_wal_size', 'autovacuum_vacuum_scale_factor',
               'autovacuum_vacuum_cost_limit', 'fillfactor')
ORDER BY name;

\echo '## Схемы: данные, индексы, TOAST'
SELECT n.nspname AS schema,
       pg_size_pretty(sum(pg_relation_size(c.oid))) AS heap,
       pg_size_pretty(sum(pg_indexes_size(c.oid))) AS indexes,
       pg_size_pretty(sum(coalesce(pg_total_relation_size(c.reltoastrelid), 0))) AS toast,
       pg_size_pretty(sum(pg_total_relation_size(c.oid))) AS total
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'm') AND n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg_toast%'
GROUP BY n.nspname ORDER BY sum(pg_total_relation_size(c.oid)) DESC;

\echo '## Таблицы (партиции свёрнуты в родителя): 40 крупнейших'
WITH rel AS (
  SELECT c.oid, coalesce(parent.oid, c.oid) AS root
  FROM pg_class c
  LEFT JOIN pg_inherits i ON i.inhrelid = c.oid
  LEFT JOIN pg_class parent ON parent.oid = i.inhparent
  WHERE c.relkind IN ('r', 'm')
)
SELECT root::regclass AS relation,
       count(*) AS parts,
       sum(greatest(cl.reltuples, 0))::bigint AS rows_estimate,
       pg_size_pretty(sum(pg_relation_size(rel.oid))) AS heap,
       pg_size_pretty(sum(pg_indexes_size(rel.oid))) AS indexes,
       pg_size_pretty(sum(coalesce(pg_total_relation_size(cl.reltoastrelid), 0))) AS toast,
       pg_size_pretty(sum(pg_total_relation_size(rel.oid))) AS total,
       sum(pg_total_relation_size(rel.oid)) AS total_bytes,
       round(sum(pg_relation_size(rel.oid) + coalesce(pg_total_relation_size(cl.reltoastrelid), 0))
             / nullif(sum(greatest(cl.reltuples, 0)), 0))::bigint AS bytes_per_row_no_index
FROM rel JOIN pg_class cl ON cl.oid = rel.oid
JOIN pg_namespace n ON n.oid = cl.relnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
GROUP BY root ORDER BY total_bytes DESC LIMIT 40;

\echo '## Индексы: 40 крупнейших и их использование с момента сброса статистики'
SELECT s.schemaname || '.' || s.relname AS "table", s.indexrelname AS index,
       pg_size_pretty(pg_relation_size(s.indexrelid)) AS size,
       s.idx_scan, x.indisunique AS "unique", x.indisprimary AS "primary"
FROM pg_stat_all_indexes s JOIN pg_index x ON x.indexrelid = s.indexrelid
WHERE s.schemaname NOT IN ('pg_catalog', 'information_schema') AND s.schemaname NOT LIKE 'pg_toast%'
ORDER BY pg_relation_size(s.indexrelid) DESC LIMIT 40;

\echo '## Неиспользуемые неуникальные индексы крупнее 8 МБ'
SELECT s.schemaname || '.' || s.relname AS "table", s.indexrelname AS index,
       pg_size_pretty(pg_relation_size(s.indexrelid)) AS size, s.idx_scan
FROM pg_stat_all_indexes s JOIN pg_index x ON x.indexrelid = s.indexrelid
WHERE s.idx_scan = 0 AND NOT x.indisunique AND NOT x.indisprimary
  AND pg_relation_size(s.indexrelid) > 8 * 1024 * 1024
ORDER BY pg_relation_size(s.indexrelid) DESC;

\echo '## Мёртвые строки и вакуум: 20 таблиц с наибольшим числом мёртвых строк'
SELECT schemaname || '.' || relname AS "table", n_live_tup, n_dead_tup,
       round(100.0 * n_dead_tup / nullif(n_live_tup + n_dead_tup, 0), 1) AS dead_pct,
       last_autovacuum, last_vacuum, n_tup_ins, n_tup_upd, n_tup_del
FROM pg_stat_all_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema') AND schemaname NOT LIKE 'pg_toast%'
ORDER BY n_dead_tup DESC LIMIT 20;

\echo '## Упакованная история (0059): плотность'
SELECT count(*) AS posts, sum(point_count) AS points,
       round(avg(point_count), 1) AS points_per_post,
       pg_size_pretty(pg_total_relation_size('ingest.publication_metric_history')) AS total,
       round(pg_total_relation_size('ingest.publication_metric_history')::numeric / nullif(sum(point_count), 0), 1)
         AS bytes_per_point_with_indexes
FROM ingest.publication_metric_history;

\echo '## Упакованная история: вклад каждого массива (сжатый размер на точку, байт)'
WITH t AS (
  SELECT sum(point_count) AS n,
       sum(pg_column_size(snapshot_id)) AS snapshot_id,
       sum(pg_column_size(observed_at)) AS observed_at,
       sum(pg_column_size(collected_lag)) AS collected_lag,
       sum(pg_column_size(created_lag)) AS created_lag,
       sum(pg_column_size(age_residual)) AS age_residual,
       sum(pg_column_size(bucket_residual)) AS bucket_residual,
       sum(pg_column_size(run_seq)) AS run_seq,
       sum(pg_column_size(views_count)) AS views_count,
       sum(pg_column_size(reactions_count)) AS reactions_count,
       sum(pg_column_size(comments_count)) AS comments_count,
       sum(pg_column_size(shares_count)) AS shares_count,
       sum(pg_column_size(codes)) AS codes,
       sum(pg_column_size(correction_sequence)) AS correction_sequence,
       sum(pg_column_size(supersedes_snapshot_id)) AS supersedes_snapshot_id,
       sum(pg_column_size(correction_reason)) AS correction_reason,
       sum(pg_column_size(semantics_version)) AS semantics_version,
       sum(pg_column_size(capability_version)) AS capability_version,
       sum(pg_column_size(evidence_id)) AS evidence_id,
       sum(pg_column_size(reaction_ref)) AS reaction_ref,
       sum(pg_column_size(reaction_dict)) AS reaction_dict
  FROM ingest.publication_metric_history TABLESAMPLE SYSTEM (2))
SELECT v.column_name, round(v.bytes::numeric / nullif(t.n, 0), 2) AS bytes_per_point
FROM t, LATERAL (VALUES
  ('snapshot_id', t.snapshot_id),
  ('observed_at', t.observed_at),
  ('collected_lag', t.collected_lag),
  ('created_lag', t.created_lag),
  ('age_residual', t.age_residual),
  ('bucket_residual', t.bucket_residual),
  ('run_seq', t.run_seq),
  ('views_count', t.views_count),
  ('reactions_count', t.reactions_count),
  ('comments_count', t.comments_count),
  ('shares_count', t.shares_count),
  ('codes', t.codes),
  ('correction_sequence', t.correction_sequence),
  ('supersedes_snapshot_id', t.supersedes_snapshot_id),
  ('correction_reason', t.correction_reason),
  ('semantics_version', t.semantics_version),
  ('capability_version', t.capability_version),
  ('evidence_id', t.evidence_id),
  ('reaction_ref', t.reaction_ref),
  ('reaction_dict', t.reaction_dict)) AS v(column_name, bytes)
ORDER BY 2 DESC NULLS LAST;

\echo '## Горячий слой замеров: строки и возраст'
SELECT (SELECT sum(greatest(reltuples, 0))::bigint FROM pg_class c JOIN pg_inherits i ON i.inhrelid = c.oid
         WHERE i.inhparent = 'ingest.publication_metric_snapshot'::regclass) AS hot_rows_estimate,
       (SELECT now() - min(observed_at) FROM (
          SELECT observed_at FROM ingest.publication_metric_snapshot ORDER BY observed_at LIMIT 1) t) AS oldest_hot_age;

\echo '## Горячие партиции замеров и реакций: размер на живую строку'
\echo 'У свежей партиции ~400 байт данных и ~360 байт индексов на строку; много больше — пустое место после упаковки.'
SELECT c.oid::regclass AS partition, greatest(s.n_live_tup, 0) AS live_rows,
       pg_size_pretty(pg_relation_size(c.oid)) AS heap,
       pg_size_pretty(pg_indexes_size(c.oid)) AS indexes,
       pg_relation_size(c.oid) / nullif(s.n_live_tup, 0) AS heap_bytes_per_row,
       pg_indexes_size(c.oid) / nullif(s.n_live_tup, 0) AS index_bytes_per_row
FROM pg_inherits h
JOIN pg_class c ON c.oid = h.inhrelid
LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
WHERE h.inhparent IN ('ingest.publication_metric_snapshot'::regclass, 'ingest.reaction_breakdown'::regclass)
  AND pg_total_relation_size(c.oid) > 1024 * 1024
ORDER BY pg_total_relation_size(c.oid) DESC;

\echo '## Чтения таблиц: из памяти или с диска (15 таблиц с наибольшим чтением с диска)'
SELECT schemaname || '.' || relname AS "table",
       heap_blks_read + coalesce(idx_blks_read, 0) AS blocks_from_disk,
       round(100.0 * (heap_blks_hit + coalesce(idx_blks_hit, 0))
             / nullif(heap_blks_hit + coalesce(idx_blks_hit, 0) + heap_blks_read + coalesce(idx_blks_read, 0), 0), 1) AS hit_pct
FROM pg_statio_user_tables
ORDER BY heap_blks_read + coalesce(idx_blks_read, 0) DESC
LIMIT 15;

\echo '## Самые дорогие запросы (pg_stat_statements, если установлен)'
SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS has_pgss
\gset
\if :has_pgss
SELECT calls, round(total_exec_time) AS total_ms, round(mean_exec_time::numeric, 1) AS mean_ms,
       rows, shared_blks_read, temp_blks_written,
       left(regexp_replace(query, '\s+', ' ', 'g'), 220) AS query
FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 25;
\else
\echo 'pg_stat_statements не установлен'
\endif

ROLLBACK;
