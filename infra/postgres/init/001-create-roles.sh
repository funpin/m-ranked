#!/usr/bin/env bash
set -Eeuo pipefail

# Runs only while the official PostgreSQL image initializes a new data volume.
# Passwords are passed as psql variables so they are quoted as SQL literals and
# never interpolated into executable SQL text.

required_variables=(
  MIGRATION_DB_PASSWORD
  API_READ_DB_PASSWORD
  API_WRITE_ADMIN_DB_PASSWORD
  COLLECTOR_INGEST_DB_PASSWORD
  BACKUP_DB_PASSWORD
  MIGRATION_BRIDGE_DB_PASSWORD
  MAINTENANCE_DB_PASSWORD
)

for variable_name in "${required_variables[@]}"; do
  if [[ -z "${!variable_name:-}" ]]; then
    echo "required database role secret is missing: ${variable_name}" >&2
    exit 1
  fi
done

psql \
  --username "${POSTGRES_USER}" \
  --dbname "${POSTGRES_DB}" \
  --set ON_ERROR_STOP=1 \
  --set migration_password="${MIGRATION_DB_PASSWORD}" \
  --set api_read_password="${API_READ_DB_PASSWORD}" \
  --set api_write_admin_password="${API_WRITE_ADMIN_DB_PASSWORD}" \
  --set collector_ingest_password="${COLLECTOR_INGEST_DB_PASSWORD}" \
  --set backup_password="${BACKUP_DB_PASSWORD}" \
  --set migration_bridge_password="${MIGRATION_BRIDGE_DB_PASSWORD}" \
  --set maintenance_password="${MAINTENANCE_DB_PASSWORD}" <<'SQL'
SELECT format('CREATE ROLE migration_owner LOGIN PASSWORD %L', :'migration_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'migration_owner') \gexec
ALTER ROLE migration_owner WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT PASSWORD :'migration_password';

SELECT format('CREATE ROLE api_read LOGIN PASSWORD %L', :'api_read_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'api_read') \gexec
ALTER ROLE api_read WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION INHERIT PASSWORD :'api_read_password';

SELECT format('CREATE ROLE api_write_admin LOGIN PASSWORD %L', :'api_write_admin_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'api_write_admin') \gexec
ALTER ROLE api_write_admin WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION INHERIT PASSWORD :'api_write_admin_password';

SELECT format('CREATE ROLE collector_ingest LOGIN PASSWORD %L', :'collector_ingest_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collector_ingest') \gexec
ALTER ROLE collector_ingest WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT PASSWORD :'collector_ingest_password';

SELECT format('CREATE ROLE backup LOGIN REPLICATION PASSWORD %L', :'backup_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'backup') \gexec
ALTER ROLE backup WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE REPLICATION NOINHERIT PASSWORD :'backup_password';

SELECT format('CREATE ROLE migration_bridge LOGIN PASSWORD %L', :'migration_bridge_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'migration_bridge') \gexec
ALTER ROLE migration_bridge WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT PASSWORD :'migration_bridge_password';

SELECT format('CREATE ROLE maintenance LOGIN PASSWORD %L', :'maintenance_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'maintenance') \gexec
ALTER ROLE maintenance WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT PASSWORD :'maintenance_password';

GRANT api_read TO api_write_admin;
GRANT pg_monitor TO backup;

SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format(
  'GRANT CONNECT ON DATABASE %I TO migration_owner, api_read, api_write_admin, collector_ingest, backup, migration_bridge, maintenance',
  current_database()
) \gexec
SELECT format('GRANT CREATE, TEMPORARY ON DATABASE %I TO migration_owner', current_database()) \gexec
SELECT format('ALTER DATABASE %I SET timezone TO %L', current_database(), 'UTC') \gexec

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA IF NOT EXISTS flyway AUTHORIZATION migration_owner;
REVOKE ALL ON SCHEMA flyway FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA flyway TO migration_owner;
SQL
