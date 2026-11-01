#!/usr/bin/env bash
# Еженедельная перестройка индексов с постоянной сменой ключей (0061) и
# индексов горячего слоя замеров: reindex-churn.sql суперпользователем
# контейнера базы, вне транзакции. На Сервере 1 MRANKED_REINDEX_SQL выбирает
# свой список из того же каталога, reindex-collector-churn.sql.
#
# REINDEX CONCURRENTLY строит новый индекс рядом со старым: на время сборки
# нужно ещё столько же места, сколько занимает самый крупный из них. Перед
# запуском это проверяет storage_guard.py на разделе с данными базы; места
# мало — служба завершается ошибкой и ничего не начинает.
set -Eeuo pipefail
container=${MRANKED_POSTGRES_CONTAINER:-mranked-target-postgres-1}
here=$(dirname "$(readlink -f "$0")")
sql_name=${MRANKED_REINDEX_SQL:-reindex-churn.sql}
if [[ ! $sql_name =~ ^[a-z0-9-]+\.sql$ ]]; then
  echo "MRANKED_REINDEX_SQL must name a file in operations/sql" >&2
  exit 2
fi
script=$here/../sql/$sql_name
psql_db() {
  docker exec -i "$container" sh -c 'psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-postgres}" -X -q "$@"' psql "$@"
}

# Самый крупный индекс из тех, что будут перестроены: названные в выбранном
# списке и, для reindex-churn.sql, индексы партиций горячего слоя замеров.
names=$(grep -oE 'REINDEX INDEX CONCURRENTLY [a-z0-9_.]+' "$script" | awk '{print $4}' | paste -sd' ' -)
partitions=$([[ $sql_name == reindex-churn.sql ]] && echo on || echo off)
largest=$(psql_db -At --set "names=$names" --set "partitions=$partitions" <<'SQL'
SELECT coalesce(max(pg_relation_size(i.indexrelid)), 0)
  FROM pg_index i
  LEFT JOIN pg_inherits h ON h.inhrelid = i.indrelid
 WHERE i.indisvalid
   AND (i.indexrelid::regclass::text = ANY (string_to_array(:'names', ' '))
        OR (:'partitions' = 'on' AND h.inhparent IN (
          'ingest.publication_metric_snapshot'::regclass, 'ingest.reaction_breakdown'::regclass)));
SQL
)
# Раздел с данными базы — источник тома, смонтированного в /var/lib/postgresql.
data_path=$(docker inspect --format '{{range .Mounts}}{{if eq (printf "%.19s" .Destination) "/var/lib/postgresql"}}{{.Source}}{{"\n"}}{{end}}{{end}}' "$container" | head -n 1)
python3 "$here/storage_guard.py" check --path "${data_path:-/}" \
  --peak-bytes "$(( ${largest:-0} + 268435456 ))" --reserve-percent "${REINDEX_RESERVE_PERCENT:-10}"

psql_db < "$script"
