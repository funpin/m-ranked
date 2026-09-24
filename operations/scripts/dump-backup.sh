#!/usr/bin/env bash
# Снимок базы целиком в формате pg_dump и проверка снятого.
#
# Штатный контур резервирования построен на pgBackRest с архивом WAL; там, где
# его нет, эта задача даёт хотя бы регулярный целостный снимок. Восстановление
# на произвольную точку она не заменяет — только на момент снимка.
set -Eeuo pipefail

umask 077

: "${BACKUP_DATABASE:?BACKUP_DATABASE is required}"
: "${BACKUP_DB_USER:?BACKUP_DB_USER is required}"
: "${BACKUP_DIR:=/var/backups/m-ranked}"
# Approved deployment may select one; previous restore-verified copy is pinned.
: "${BACKUP_KEEP:=1}"
: "${BACKUP_MAX_DUMP_BYTES:=5000000000}"
: "${BACKUP_RESERVE_BYTES:=11000000000}"
: "${MRANKED_DB_CONTAINER:?MRANKED_DB_CONTAINER is required}"
# Потолок скорости потока. Дамп читается медленнее — pg_dump ждёт записи, и
# вместе с ним притормаживает серверный COPY: без потолка контрольный запуск
# 24.09 занял процессор, а доставка данных отстала с 40 до 159 секунд.
: "${BACKUP_MAX_BYTES_PER_SECOND:=10000000}"
: "${BACKUP_CPUS:=0.5}"
: "${BACKUP_METRICS_FILE:=}"
# Неудачный запуск намеренно оставляет .partial для разбора: по нему
# видно, на чём дамп оборвался. Но разбирают его в тот же день, а файл
# весит столько же, сколько готовый снимок, и следующий сбой добавляет
# ещё один. Без срока годности они копятся молча.
: "${BACKUP_PARTIAL_MAX_AGE_HOURS:=24}"

if [[ ! "$BACKUP_KEEP" =~ ^[0-9]+$ ]] || (( BACKUP_KEEP < 1 || BACKUP_KEEP > 90 )); then
  echo "BACKUP_KEEP must be between 1 and 90" >&2
  exit 64
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
exec 9>"$BACKUP_DIR/.backup.lock"
flock -n 9 || { echo "backup already running" >&2; exit 75; }
script_dir="$(cd "$(dirname "$0")" && pwd)"

if [[ ! "$BACKUP_MAX_BYTES_PER_SECOND" =~ ^[1-9][0-9]*$ ]] || (( BACKUP_MAX_BYTES_PER_SECOND < 1000000 )); then
  echo "BACKUP_MAX_BYTES_PER_SECOND must be at least 1000000" >&2
  exit 64
fi
if [[ ! "$BACKUP_CPUS" =~ ^(0\.[1-9][0-9]?|[1-2](\.[0-9]+)?)$ ]]; then
  echo "BACKUP_CPUS must be between 0.1 and 2" >&2
  exit 64
fi

if [[ ! "$BACKUP_PARTIAL_MAX_AGE_HOURS" =~ ^[0-9]+$ ]] \
   || (( BACKUP_PARTIAL_MAX_AGE_HOURS < 1 || BACKUP_PARTIAL_MAX_AGE_HOURS > 168 )); then
  echo "BACKUP_PARTIAL_MAX_AGE_HOURS must be between 1 and 168" >&2
  exit 64
fi

# Чистим до снятия нового снимка: место нужно именно сейчас.
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'mranked-*.dump.partial' \
  -mmin "+$(( BACKUP_PARTIAL_MAX_AGE_HOURS * 60 ))" -delete

python3 "$script_dir/storage_guard.py" check --path "$BACKUP_DIR" \
  --peak-bytes "$BACKUP_MAX_DUMP_BYTES" --reserve-bytes "$BACKUP_RESERVE_BYTES"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$BACKUP_DIR/mranked-$stamp.dump"
partial="$target.partial"
started=$(date -u +%s)

# pg_dump работает в отдельном короткоживущем контейнере в сети базы, а не
# через docker exec: сигнал остановки юнита до процесса внутри exec не
# доходит, и 24.09 после остановки задачи pg_dump продолжал работать сам по
# себе. Свой контейнер с именем задачи останавливается при любом выходе
# скрипта, а его сессия в базе снимается по application_name.
image="$(docker inspect --format '{{.Image}}' "$MRANKED_DB_CONTAINER")"
dumper="mranked-backup-$stamp"
cleanup() {
  status=$?
  docker kill "$dumper" >/dev/null 2>&1 || true
  docker exec "$MRANKED_DB_CONTAINER" psql -U "$BACKUP_DB_USER" -d "$BACKUP_DATABASE" -At -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name = '$dumper'" \
    >/dev/null 2>&1 || true
  # Недоснятый файл этого запуска не нужен никому: иначе каждая прерванная
  # попытка оставляла бы на диске до суток по гигабайту. Удачный снимок к
  # этому моменту уже переименован, и под этим именем файла нет.
  rm -f -- "$partial"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 143' TERM INT HUP

# Пароль передаётся по имени переменной, а не значением в аргументах: аргументы
# видны в списке процессов любому пользователю машины.
export PGPASSWORD
# Снимок пишется во временное имя: недоснятый файл не должен выглядеть готовым.
docker run --rm -i --name "$dumper" --network "container:$MRANKED_DB_CONTAINER" \
  --cpus "$BACKUP_CPUS" --memory 512m --pids-limit 64 \
  -e PGPASSWORD -e PGAPPNAME="$dumper" "$image" \
  pg_dump -h 127.0.0.1 -U "$BACKUP_DB_USER" -d "$BACKUP_DATABASE" -Fc --no-password \
  | python3 "$script_dir/backup-stream.py" \
    "$partial" "$BACKUP_MAX_DUMP_BYTES" "$BACKUP_RESERVE_BYTES" "$BACKUP_MAX_BYTES_PER_SECOND" &
wait $!

# Decode every archive member; TOC alone does not detect truncated payload.
# This is integrity verification, not an actual database restore.
docker run --rm --name "$dumper-verify" --network none --memory 256m --cpus "$BACKUP_CPUS" \
  -v "$BACKUP_DIR:/backups:ro" "$image" \
  pg_restore --file=/dev/null "/backups/$(basename "$partial")"
size=$(stat -c %s "$partial")
if (( size < 1048576 )); then
  echo "dump looks too small: $size bytes" >&2
  exit 65
fi
mv "$partial" "$target"
# Verification receipts contain SHA256 and basename, written only after a real
# isolated restore. Preserve every attested copy until a newer attested copy
# exists. No backup deletion based just on age, filename, or TOC.
python3 "$script_dir/rotate-dumps.py" "$BACKUP_DIR" "$BACKUP_KEEP"

elapsed=$(( $(date -u +%s) - started ))
if [[ -n "$BACKUP_METRICS_FILE" ]]; then
  python3 - "$BACKUP_METRICS_FILE" "$size" "$elapsed" <<'PYMETRICS'
import os, pathlib, sys, tempfile, time
path = pathlib.Path(sys.argv[1])
fd, name = tempfile.mkstemp(prefix=".backup-", dir=path.parent)
try:
    with os.fdopen(fd, "w") as stream:
        stream.write(f"mranked_backup_last_success_unixtime {time.time()}\n")
        stream.write(f"mranked_backup_last_bytes {int(sys.argv[2])}\n")
        stream.write(f"mranked_backup_last_duration_seconds {int(sys.argv[3])}\n")
        os.fchmod(stream.fileno(), 0o644)
    os.replace(name, path)
finally:
    pathlib.Path(name).unlink(missing_ok=True)
PYMETRICS
fi
echo "backup $target ($(numfmt --to=iec "$size")) in ${elapsed}s; kept $(ls -1 "$BACKUP_DIR"/mranked-*.dump | wc -l)"
