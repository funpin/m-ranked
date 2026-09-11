\set ON_ERROR_STOP on
\pset pager off
\timing on

BEGIN TRANSACTION READ ONLY;
SET LOCAL statement_timeout = '2min';
SET LOCAL lock_timeout = '2s';

SELECT current_database() AS database_name,
       current_setting('server_version') AS server_version,
       pg_size_pretty(pg_database_size(current_database())) AS database_size,
       pg_postmaster_start_time() AS postmaster_started_at,
       now() - pg_postmaster_start_time() AS postmaster_uptime,
       stats_reset
FROM pg_stat_database
WHERE datname = current_database();

-- Physical partition hierarchy. Parent indexes are virtual; child indexes own
-- the bytes and write cost reported below.
SELECT parent_namespace.nspname AS parent_schema,
       parent.relname AS parent_name,
       child_namespace.nspname AS child_schema,
       child.relname AS child_name,
       child.relkind,
       pg_get_expr(child.relpartbound, child.oid) AS partition_bound
FROM pg_inherits
JOIN pg_class AS parent ON parent.oid = pg_inherits.inhparent
JOIN pg_namespace AS parent_namespace ON parent_namespace.oid = parent.relnamespace
JOIN pg_class AS child ON child.oid = pg_inherits.inhrelid
JOIN pg_namespace AS child_namespace ON child_namespace.oid = child.relnamespace
WHERE parent_namespace.nspname IN ('ingest', 'analytics')
ORDER BY parent_schema, parent_name, child_name;

-- Largest physical heap/partition relations.
SELECT namespace.nspname AS schema_name,
       relation.relname AS relation_name,
       relation.relkind,
       pg_total_relation_size(relation.oid) AS total_bytes,
       pg_relation_size(relation.oid) AS heap_bytes,
       pg_indexes_size(relation.oid) AS index_bytes,
       round(
           pg_indexes_size(relation.oid)::numeric
           / nullif(pg_relation_size(relation.oid), 0), 3
       ) AS index_heap_ratio,
       pg_size_pretty(pg_total_relation_size(relation.oid)) AS total_size
FROM pg_class AS relation
JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
  AND relation.relkind IN ('r', 'm')
ORDER BY total_bytes DESC
LIMIT 100;

-- Logical and physical index inventory with constraint ownership and usage.
SELECT table_namespace.nspname AS table_schema,
       table_relation.relname AS table_name,
       index_relation.relname AS index_name,
       index_relation.relkind AS index_relkind,
       pg_relation_size(index_relation.oid) AS index_bytes,
       pg_size_pretty(pg_relation_size(index_relation.oid)) AS index_size,
       coalesce(index_stats.idx_scan, 0) AS idx_scan,
       coalesce(index_stats.idx_tup_read, 0) AS idx_tup_read,
       coalesce(index_stats.idx_tup_fetch, 0) AS idx_tup_fetch,
       constraint_record.contype AS constraint_type,
       index_catalog.indisunique,
       index_catalog.indisprimary,
       index_catalog.indisvalid,
       pg_get_indexdef(index_relation.oid) AS index_definition
FROM pg_index AS index_catalog
JOIN pg_class AS index_relation ON index_relation.oid = index_catalog.indexrelid
JOIN pg_class AS table_relation ON table_relation.oid = index_catalog.indrelid
JOIN pg_namespace AS table_namespace ON table_namespace.oid = table_relation.relnamespace
LEFT JOIN pg_stat_all_indexes AS index_stats
       ON index_stats.indexrelid = index_relation.oid
LEFT JOIN pg_constraint AS constraint_record
       ON constraint_record.conindid = index_relation.oid
WHERE table_namespace.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY index_bytes DESC, table_schema, table_name, index_name;

-- Exact duplicate physical index definitions after removing the index name.
WITH normalized AS (
    SELECT index_catalog.indrelid,
           index_catalog.indexrelid,
           regexp_replace(
               pg_get_indexdef(index_catalog.indexrelid),
               '^CREATE( UNIQUE)? INDEX [^ ]+ ',
               'CREATE\1 INDEX '
           ) AS normalized_definition
    FROM pg_index AS index_catalog
)
SELECT table_relation.oid::regclass AS table_name,
       array_agg(index_relation.oid::regclass ORDER BY index_relation.relname) AS indexes,
       normalized_definition
FROM normalized
JOIN pg_class AS table_relation ON table_relation.oid = normalized.indrelid
JOIN pg_class AS index_relation ON index_relation.oid = normalized.indexrelid
GROUP BY table_relation.oid, normalized_definition
HAVING count(*) > 1
ORDER BY table_relation.oid::regclass::text;

-- Table write/read behaviour. Low idx_scan is evidence only, never a drop rule.
SELECT schemaname, relname,
       n_live_tup, n_dead_tup,
       n_tup_ins, n_tup_upd, n_tup_del, n_tup_hot_upd,
       seq_scan, idx_scan,
       last_vacuum, last_autovacuum, last_analyze, last_autoanalyze
FROM pg_stat_all_tables
WHERE schemaname IN ('ingest', 'analytics')
ORDER BY n_tup_ins + n_tup_upd + n_tup_del DESC;

-- Representative widths and sparsity. The recent-partition LIMIT keeps this
-- bounded; run exact distributions separately only on staging if required.
WITH sample AS (
    SELECT snapshot.*
    FROM ingest.publication_metric_snapshot AS snapshot
    WHERE published_month >= date_trunc('month', current_date) - interval '2 months'
    LIMIT 100000
)
SELECT count(*) AS sampled_rows,
       avg(pg_column_size(snapshot))::numeric(12,2) AS avg_row_bytes,
       percentile_cont(ARRAY[0.5, 0.95]) WITHIN GROUP (
           ORDER BY pg_column_size(snapshot)
       ) AS row_bytes_p50_p95,
       avg(pg_column_size(source_fingerprint))::numeric(12,2) AS avg_fingerprint_bytes,
       percentile_cont(ARRAY[0.5, 0.95]) WITHIN GROUP (
           ORDER BY pg_column_size(source_fingerprint)
       ) AS fingerprint_bytes_p50_p95,
       max(pg_column_size(source_fingerprint)) AS fingerprint_bytes_max,
       avg(pg_column_size(metric_evidence))::numeric(12,2) AS avg_evidence_bytes,
       percentile_cont(ARRAY[0.5, 0.95]) WITHIN GROUP (
           ORDER BY pg_column_size(metric_evidence)
       ) AS evidence_bytes_p50_p95,
       count(*) FILTER (WHERE metric_evidence = '{}'::jsonb) AS empty_evidence_rows
FROM sample AS snapshot;

WITH sample AS (
    SELECT reaction.*
    FROM ingest.reaction_breakdown AS reaction
    WHERE snapshot_published_month >= date_trunc('month', current_date) - interval '2 months'
    LIMIT 100000
)
SELECT count(*) AS sampled_rows,
       avg(pg_column_size(reaction))::numeric(12,2) AS avg_row_bytes,
       avg(pg_column_size(reaction_key))::numeric(12,2) AS avg_key_bytes,
       percentile_cont(ARRAY[0.5, 0.95]) WITHIN GROUP (
           ORDER BY pg_column_size(reaction_key)
       ) AS key_bytes_p50_p95,
       max(pg_column_size(reaction_key)) AS key_bytes_max,
       count(DISTINCT reaction_key) AS sampled_key_cardinality
FROM sample AS reaction;

SELECT outcome, reason_code, count(*) AS rows
FROM ingest.deletion_observation
GROUP BY outcome, reason_code
ORDER BY rows DESC;

-- Estimate unchanged consecutive metric states without assuming that the full
-- source fingerprint is stable across polls.
WITH states AS (
    SELECT snapshot.publication_id, snapshot.observed_at,
           snapshot.correction_sequence, snapshot.id,
           jsonb_build_object(
               'views', views_count, 'reactions', reactions_count,
               'comments', comments_count, 'shares', shares_count,
               'quality', quality, 'views_quality', views_quality,
               'reactions_quality', reactions_quality,
               'comments_quality', comments_quality,
               'shares_quality', shares_quality,
               'interval_uncertain', interval_uncertain,
               'synthetic', synthetic,
               'metric_semantics_version', metric_semantics_version,
               'capability_version', capability_version,
               'metric_evidence', metric_evidence,
               'reaction_breakdown', coalesce((
                   SELECT jsonb_object_agg(
                       reaction.reaction_key, reaction.reaction_count
                       ORDER BY reaction.reaction_key
                   )
                   FROM ingest.reaction_breakdown AS reaction
                   WHERE reaction.snapshot_published_month = snapshot.published_month
                     AND reaction.snapshot_id = snapshot.id
               ), '{}'::jsonb)
           ) AS semantic_state
    FROM ingest.publication_metric_snapshot AS snapshot
    WHERE published_month >= date_trunc('month', current_date) - interval '2 months'
), sampled AS (
    SELECT states.*,
           lag(semantic_state) OVER (
               PARTITION BY publication_id
               ORDER BY observed_at, correction_sequence, id
           ) AS prior_state
    FROM states
)
SELECT count(*) FILTER (WHERE prior_state IS NOT NULL) AS comparable_rows,
       count(*) FILTER (WHERE prior_state = semantic_state) AS unchanged_rows
FROM sampled;

SELECT EXISTS (
    SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'
) AS has_pg_stat_statements
\gset

\if :has_pg_stat_statements
SELECT calls, total_exec_time, mean_exec_time, rows,
       shared_blks_hit, shared_blks_read, shared_blks_dirtied,
       temp_blks_read, temp_blks_written, wal_bytes,
       left(query, 1000) AS query
FROM pg_stat_statements
WHERE query ~ '(publication_metric_snapshot|reaction_breakdown|deletion_observation|publication_availability_)'
ORDER BY total_exec_time DESC
LIMIT 100;
\else
\echo 'pg_stat_statements is not installed; use code-level query discovery.'
\endif

ROLLBACK;
