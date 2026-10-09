#!/usr/bin/env bash
# Отчёт для решений по хранению, скорости страниц и резервным копиям.
#
# Только чтение: SQL в транзакции READ ONLY (operations/sql/storage-report.sql),
# список дампов, журнал службы дампа и журнал доступа nginx. Ничего не
# останавливает и не пишет, работает на пониженном приоритете. В выводе нет
# адресов, user agent и содержимого строк — только размеры, тайминги и
# шаблоны путей; его можно пересылать как есть.
#
#   sudo operations/scripts/storage-report.sh > storage-report.txt
set -Eeuo pipefail

: "${MRANKED_DB_CONTAINER:=m-ranked-postgres}"
: "${BACKUP_DIR:=/var/backups/m-ranked}"
: "${ACCESS_LOG:=/var/log/nginx/m-ranked-access.log}"
: "${REPORT_LOG_HOURS:=24}"
script_dir="$(cd "$(dirname "$0")" && pwd)"
sql="$script_dir/../sql/storage-report.sql"

renice -n 15 -p $$ >/dev/null 2>&1 || true
ionice -c 3 -p $$ >/dev/null 2>&1 || true

section() { printf '\n# %s\n' "$1"; }

section "Диск"
df -h / | sed -n '1,2p'
du -sh "$BACKUP_DIR" 2>/dev/null || true

section "База"
docker exec -i "$MRANKED_DB_CONTAINER" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -q' < "$sql"

section "Нагрузка базы: что выполняется (${REPORT_ACTIVITY_SAMPLES:-30} замеров раз в 2 с)"
# pg_stat_statements нет, поэтому — выборка pg_stat_activity: какие запросы
# чаще всего застаёшь за работой. Литералы заменены на «?»: в выводе только
# форма запроса, без идентификаторов и значений.
for _ in $(seq 1 "${REPORT_ACTIVITY_SAMPLES:-30}"); do
  docker exec -i "$MRANKED_DB_CONTAINER" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -At -F " | "' 2>/dev/null <<'SQL' || true
SELECT coalesce(nullif(application_name, ''), '-'), coalesce(wait_event_type, 'CPU'),
       left(regexp_replace(regexp_replace(regexp_replace(query, '\s+', ' ', 'g'), '''[^'']*''', '?', 'g'), '\m\d+\M', '?', 'g'), 160)
FROM pg_stat_activity
WHERE state = 'active' AND pid <> pg_backend_pid() AND backend_type = 'client backend';
SQL
  sleep 2
done | python3 -I -c '
import collections, sys
seen = collections.Counter(line.rstrip("\n") for line in sys.stdin if line.strip())
print("замечено  приложение | ожидание | запрос")
for line, count in seen.most_common(20):
    print(f"{count:8}  {line}")
'

section "Дампы на диске"
ls -l --time-style=+%F_%R "$BACKUP_DIR"/mranked-*.dump 2>/dev/null | awk '{printf "%s  %.2f GB  %s\n", $6, $5 / 1e9, $7}' || true

section "Последние запуски дампа (14 суток)"
journalctl -u m-ranked-target-dump-backup.service --since -14d -o short-iso --no-pager 2>/dev/null \
  | grep -E 'Starting|Finished|Failed|Consumed|dump looks|backup already' | tail -n 40 || true

section "Контейнеры проекта"
docker stats --no-stream --format '{{.Name}}  CPU {{.CPUPerc}}  RAM {{.MemUsage}}' \
  $(docker ps --filter name=m-ranked --format '{{.Names}}') 2>/dev/null || true

section "Страницы за ${REPORT_LOG_HOURS} ч: время ответа по шаблонам путей (люди)"
python3 -I - "$ACCESS_LOG" "$REPORT_LOG_HOURS" <<'PY'
import math, re, sys, time
from collections import defaultdict
from pathlib import Path

path, hours = Path(sys.argv[1]), float(sys.argv[2])
line_re = re.compile(r'^\S+ \[([^\]]+)\] "(\S+) (\S+)[^"]*" (\d{3}) (\d+) ([\d.]+) (\w+) (\S+) "')
bots = {"ai_user", "ai_search", "ai_training", "crawler"}
cutoff = time.time() - hours * 3600
groups = defaultdict(list)
cache = defaultdict(lambda: [0, 0])
total = 0


def template(url: str) -> str:
    url = url.split("?", 1)[0]
    url = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", ":uuid", url)
    url = re.sub(r"/\d+(?=/|$)", "/:n", url)
    if url.startswith("/_next/"):
        return "/_next/*"
    return url


sources = [path] + sorted(path.parent.glob(path.name + ".1"))
for source in sources:
    try:
        stream = source.open(errors="replace")
    except OSError:
        continue
    with stream:
        for line in stream:
            match = line_re.match(line)
            if not match or match[7] in bots:
                continue
            try:
                at = time.mktime(time.strptime(match[1], "%d/%b/%Y:%H:%M:%S %z"))
            except ValueError:
                continue
            if at < cutoff:
                continue
            key = f"{match[2]} {template(match[3])}"
            groups[key].append(float(match[6]))
            hit = cache[key]
            hit[0] += match[8] in {"HIT", "STALE", "UPDATING", "REVALIDATED"}
            hit[1] += match[8] != "-"
            total += 1


def pct(values, share):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(share * len(ordered)) - 1))]


print(f"запросов людей: {total}")
print(f"{'запросов':>8} {'p50,с':>7} {'p95,с':>7} {'max,с':>7} {'кэш':>5}  шаблон")
for key, values in sorted(groups.items(), key=lambda item: -sum(item[1]))[:30]:
    hit, cached = cache[key]
    share = f"{100 * hit / cached:.0f}%" if cached else "—"
    print(f"{len(values):>8} {pct(values, .5):>7.3f} {pct(values, .95):>7.3f} {max(values):>7.3f} {share:>5}  {key}")
PY
