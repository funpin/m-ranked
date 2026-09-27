-- Metadata-only, read-only snapshot for the constrained PostgreSQL host.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '15s';

SELECT 'database_size' AS section, current_database() AS name,
       pg_database_size(current_database())::text AS value;

SELECT 'activity' AS section, state::text AS name, count(*)::text AS value
FROM pg_stat_activity
WHERE datname = current_database()
GROUP BY state;

SELECT 'setting' AS section, name,
       setting || COALESCE(' ' || unit, '') AS value
FROM pg_settings
WHERE name IN ('max_connections', 'shared_buffers', 'work_mem',
               'maintenance_work_mem', 'temp_file_limit',
               'max_parallel_workers', 'max_parallel_workers_per_gather',
               'effective_cache_size', 'wal_keep_size')
ORDER BY name;

SELECT 'temp_history' AS section, datname AS name,
       temp_files::text || ' files; ' || temp_bytes::text || ' bytes' AS value
FROM pg_stat_database
WHERE datname = current_database();

SELECT 'largest_relation' AS section,
       n.nspname || '.' || c.relname AS name,
       pg_total_relation_size(c.oid)::text AS value
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT 12;

COMMIT;
