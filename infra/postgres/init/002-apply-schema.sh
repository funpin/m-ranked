#!/usr/bin/env bash
set -Eeuo pipefail

for migration in /m-ranked-schema/*.sql; do
  psql --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" \
    --no-psqlrc --set ON_ERROR_STOP=1 --file "$migration"
done
