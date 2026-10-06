#!/usr/bin/env bash
# Еженедельная перестройка индексов с постоянной сменой ключей (0061):
# reindex-churn.sql суперпользователем контейнера базы, вне транзакции.
set -Eeuo pipefail
container=${MRANKED_POSTGRES_CONTAINER:-mranked-target-postgres-1}
script=$(dirname "$(readlink -f "$0")")/../sql/reindex-churn.sql
docker exec -i "$container" sh -c 'psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-postgres}" -X -q' < "$script"
