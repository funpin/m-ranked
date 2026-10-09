#!/usr/bin/env bash
# Еженедельная перестройка индексов с постоянной сменой ключей (0061) и
# индексов горячего слоя замеров: reindex-churn.sql суперпользователем
# контейнера базы, вне транзакции.
#
# REINDEX CONCURRENTLY строит новый индекс рядом со старым: на время сборки
# нужно ещё столько же места, сколько занимает самый крупный из них. Перед
# запуском это проверяет storage_guard.py на разделе с данными базы; места
# мало — служба завершается ошибкой и ничего не начинает.
set -Eeuo pipefail
container=${MRANKED_POSTGRES_CONTAINER:-mranked-target-postgres-1}
here=$(dirname "$(readlink -f "$0")")
script=$here/../sql/reindex-churn.sql
psql_db() {
  docker exec -i "$container" sh -c 'psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-postgres}" -X -q "$@"' psql "$@"
}

# Самый крупный индекс из тех, что будут перестроены (из обоих списков).
largest=$(psql_db -At <<'SQL'
SELECT coalesce(max(pg_relation_size(i.indexrelid)), 0)
  FROM pg_index i
  LEFT JOIN pg_inherits h ON h.inhrelid = i.indrelid
 WHERE i.indisvalid
   AND (h.inhparent IN ('ingest.publication_metric_snapshot'::regclass, 'ingest.reaction_breakdown'::regclass)
        OR i.indexrelid::regclass::text IN (
          'analytics.publication_latest_account_idx', 'analytics.publication_latest_revision_idx',
          'analytics.publication_latest_pkey', 'analytics.dataset_revision_committed_idx',
          'analytics.dataset_revision_pkey')
        OR i.indexrelid::regclass::text LIKE 'ops_and_admin.outbox_event%');
SQL
)
# Раздел с данными базы — источник тома, смонтированного в /var/lib/postgresql.
data_path=$(docker inspect --format '{{range .Mounts}}{{if eq (printf "%.19s" .Destination) "/var/lib/postgresql"}}{{.Source}}{{"\n"}}{{end}}{{end}}' "$container" | head -n 1)
python3 "$here/storage_guard.py" check --path "${data_path:-/}" \
  --peak-bytes "$(( ${largest:-0} + 268435456 ))" --reserve-percent "${REINDEX_RESERVE_PERCENT:-10}"

psql_db < "$script"
