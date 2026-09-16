#!/usr/bin/env bash
# Сторож сборщиков: поднимает того, кто завис.
#
# Restart=on-failure зависший процесс не ловит — он не падает. 16.09.2026
# сборщик MAX простоял сутки и пять часов: процесс жив, спит на сетевом
# ожидании, обход открыт с 14:43 и не закрывается, в журнале пусто. Снаружи всё
# выглядело исправным, а данные не собирались.
#
# Признак жизни — свежий обход в ingest.collection_run. Порог взят с запасом к
# самому длинному интервалу опроса, чтобы обычная пауза не считалась зависанием.
set -Eeuo pipefail

CONTAINER=${WATCHDOG_DB_CONTAINER:-mranked-production-postgres-1}
DB_USER=${WATCHDOG_DB_USER:-mranked_bootstrap}
DB_NAME=${WATCHDOG_DB_NAME:-mranked}
THRESHOLD_MINUTES=${WATCHDOG_THRESHOLD_MINUTES:-45}

query() {
  docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tAc "$1"
}

# Признак жизни — поступающие снимки, а не начало обхода: прерванный обход
# сборщик возобновляет, и его started_at остаётся прежним. По нему сторож
# считал бы живого сборщика зависшим и дёргал бы его без конца.
stale=$(query "SELECT run.platform
                 FROM ingest.collection_run run
                 JOIN ingest.publication_metric_snapshot snapshot
                   ON snapshot.collection_run_id = run.id
                  AND snapshot.collected_at > now() - interval '1 day'
                GROUP BY run.platform
               HAVING max(snapshot.collected_at) < now() - interval '${THRESHOLD_MINUTES} minutes'")

if [[ -z "${stale//[[:space:]]/}" ]]; then
  echo "сборщики свежие: ни один обход не старше ${THRESHOLD_MINUTES} мин"
  exit 0
fi

while read -r platform; do
  [[ -n "$platform" ]] || continue
  unit="m-ranked-target-collector@${platform}.service"
  age=$(query "SELECT round(extract(epoch FROM now()-max(snapshot.collected_at))/60)::int
                 FROM ingest.collection_run run
                 JOIN ingest.publication_metric_snapshot snapshot
                   ON snapshot.collection_run_id = run.id
                  AND snapshot.collected_at > now() - interval '1 day'
                WHERE run.platform='${platform}'")
  echo "сборщик ${platform} не приносит снимков ${age} мин, перезапускаю ${unit}"
  systemctl restart "$unit"
done <<< "$stale"
