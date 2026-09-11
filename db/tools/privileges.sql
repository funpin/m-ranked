\pset format unaligned
\pset fieldsep '\t'
\pset footer off
SELECT grantee, table_schema, table_name, privilege_type
  FROM information_schema.role_table_grants
 WHERE table_schema IN ('analytics','catalog','ingest','ops_and_admin','rating')
   AND grantee NOT IN ('mranked_bootstrap','migration_owner','PUBLIC')
   AND table_name !~ '_(19|20)[0-9]{2}_[0-9]{2}$'
 ORDER BY 1,2,3,4;
