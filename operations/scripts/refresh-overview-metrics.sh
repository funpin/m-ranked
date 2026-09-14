#!/usr/bin/env bash
# Пересчёт витрины карточек обзора.
#
# Один прогон считает прирост по всем публикациям с наблюдением внутри окна
# для всех четырёх периодов и раскладывает по пяти разрезам площадок. Живым
# запросом то же самое стоило шести секунд на каждое открытие экрана.
#
# Клиент psql берётся с хоста, а если задан MRANKED_DB_CONTAINER — из этого
# контейнера: на серверах, где база поднята в Docker, клиента на хосте нет.
set -Eeuo pipefail

umask 077

: "${MAINTENANCE_DATABASE_URL:?MAINTENANCE_DATABASE_URL is required}"

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
script="$root/db/tools/refresh-overview-card-metrics.sql"
if [[ ! -r "$script" ]]; then
  echo "refresh script is missing: $script" >&2
  exit 66
fi

if [[ -n "${MRANKED_DB_CONTAINER:-}" ]]; then
  runner=(docker exec -i -e "PGPASSWORD=${PGPASSWORD:-}" "$MRANKED_DB_CONTAINER" psql)
else
  : "${PGPASSFILE:?PGPASSFILE is required without MRANKED_DB_CONTAINER}"
  runner=(psql)
fi

started=$(date -u +%s)
"${runner[@]}" --no-psqlrc --quiet --set ON_ERROR_STOP=1 \
  --dbname "$MAINTENANCE_DATABASE_URL" --file - < "$script" >/dev/null
echo "overview card metrics refreshed in $(( $(date -u +%s) - started ))s"
