\set ON_ERROR_STOP on

-- Run only as the local cluster bootstrap role, connected to the postgres
-- maintenance database.  This is intentionally one-shot: an existing database
-- is never replaced implicitly.
DO $guard$
BEGIN
    IF current_database() <> 'postgres' THEN
        RAISE EXCEPTION
            'refusing UI rehearsal bootstrap in database %; expected postgres',
            current_database();
    END IF;
    IF session_user <> 'mranked_bootstrap' THEN
        RAISE EXCEPTION
            'refusing UI rehearsal bootstrap as session user %; expected mranked_bootstrap',
            session_user;
    END IF;
END
$guard$;

SELECT CASE
           WHEN EXISTS (
               SELECT 1
                 FROM pg_database
                WHERE datname = 'mranked_ui_rehearsal'
           ) THEN 'true'
           ELSE 'false'
       END AS rehearsal_database_exists
\gset

\if :rehearsal_database_exists
    \warn 'mranked_ui_rehearsal already exists; refusing to replace it'
    \quit 3
\endif

CREATE DATABASE mranked_ui_rehearsal
    OWNER migration_owner
    TEMPLATE template0
    ENCODING 'UTF8';

REVOKE ALL ON DATABASE mranked_ui_rehearsal FROM PUBLIC;
GRANT CONNECT ON DATABASE mranked_ui_rehearsal TO
    migration_owner,
    api_read,
    api_write_admin,
    collector_ingest,
    backup,
    migration_bridge,
    maintenance;
GRANT CREATE, TEMPORARY ON DATABASE mranked_ui_rehearsal TO migration_owner;
ALTER DATABASE mranked_ui_rehearsal SET timezone TO 'UTC';

\connect mranked_ui_rehearsal

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA flyway AUTHORIZATION migration_owner;
REVOKE ALL ON SCHEMA flyway FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA flyway TO migration_owner;

SELECT current_database() AS created_database,
       pg_encoding_to_char(encoding) AS encoding,
       datcollate AS collation,
       datctype AS character_type
  FROM pg_database
 WHERE datname = current_database();
