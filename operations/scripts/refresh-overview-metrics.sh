#!/usr/bin/env bash
# Пересчёт витрины карточек обзора.
#
# Один прогон считает прирост по всем публикациям с наблюдением внутри окна
# для всех четырёх периодов и раскладывает по пяти разрезам площадок. Живым
# запросом то же самое стоило шести секунд на каждое открытие экрана.
set -Eeuo pipefail

umask 077

: "${MAINTENANCE_DATABASE_URL:?MAINTENANCE_DATABASE_URL is required}"
: "${PGPASSFILE:?PGPASSFILE is required}"

script="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/db/tools/refresh-overview-card-metrics.sql"
if [[ ! -r "$script" ]]; then
  echo "refresh script is missing: $script" >&2
  exit 66
fi

started=$(date -u +%s)
psql --no-psqlrc --quiet --set ON_ERROR_STOP=1 --dbname "$MAINTENANCE_DATABASE_URL" --file "$script" >/dev/null
echo "overview card metrics refreshed in $(( $(date -u +%s) - started ))s"
