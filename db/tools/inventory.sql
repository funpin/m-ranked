\pset footer off
\pset format unaligned
\pset fieldsep '\t'

\echo === RELATIONS (non-partition-children) ===
SELECT n.nspname, c.relname, c.relkind,
       CASE WHEN c.relkind='p' THEN 'partitioned' WHEN c.relispartition THEN 'child' ELSE 'plain' END AS part,
       pg_total_relation_size(c.oid) AS total_bytes,
       pg_table_size(c.oid) AS heap_bytes,
       pg_indexes_size(c.oid) AS index_bytes
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname IN ('analytics','catalog','ingest','ops_and_admin','rating')
   AND c.relkind IN ('r','p','v','m','S')
   AND NOT c.relispartition
 ORDER BY 1,2;

\echo === PARTITION CHILD COUNTS ===
SELECT n.nspname, c.relname, count(i.inhrelid) AS children
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  LEFT JOIN pg_inherits i ON i.inhparent=c.oid
 WHERE c.relkind='p' AND n.nspname IN ('analytics','catalog','ingest','ops_and_admin','rating')
 GROUP BY 1,2 ORDER BY 1,2;

\echo === INDEXES (parents only) ===
SELECT schemaname, tablename, indexname, indexdef
  FROM pg_indexes
 WHERE schemaname IN ('analytics','catalog','ingest','ops_and_admin','rating')
   AND indexname NOT IN (SELECT c.relname FROM pg_class c WHERE c.relispartition)
 ORDER BY 1,2,3;

\echo === FUNCTIONS ===
SELECT n.nspname, p.proname, pg_get_function_identity_arguments(p.oid) AS args, l.lanname
  FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang
 WHERE n.nspname IN ('analytics','catalog','ingest','ops_and_admin','rating')
 ORDER BY 1,2,3;

\echo === VIEWS ===
SELECT n.nspname, c.relname, c.relkind
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE c.relkind IN ('v','m') AND n.nspname IN ('analytics','catalog','ingest','ops_and_admin','rating')
 ORDER BY 1,2;

\echo === CONSTRAINTS (parents only) ===
SELECT n.nspname, c.relname, con.conname, con.contype, pg_get_constraintdef(con.oid)
  FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname IN ('analytics','catalog','ingest','ops_and_admin','rating') AND NOT c.relispartition
 ORDER BY 1,2,3;

\echo === TRIGGERS ===
SELECT n.nspname, c.relname, t.tgname, pg_get_triggerdef(t.oid)
  FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE NOT t.tgisinternal AND n.nspname IN ('analytics','catalog','ingest','ops_and_admin','rating') AND NOT c.relispartition
 ORDER BY 1,2,3;

\echo === TYPES ===
SELECT n.nspname, t.typname, t.typtype
  FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
 WHERE n.nspname IN ('analytics','catalog','ingest','ops_and_admin','rating') AND t.typtype IN ('e','d','c')
   AND NOT EXISTS (SELECT 1 FROM pg_class c WHERE c.oid=t.typrelid AND c.relkind<>'c')
 ORDER BY 1,2;

\echo === EXTENSIONS ===
SELECT extname, extversion FROM pg_extension ORDER BY 1;

\echo === ROLES ===
SELECT rolname, rolcanlogin, rolsuper FROM pg_roles WHERE rolname NOT LIKE 'pg\_%' ORDER BY 1;
