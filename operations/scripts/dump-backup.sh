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

# Пароль передаётся по имени переменной, а не значением в аргументах: аргументы
# видны в списке процессов любому пользователю машины.
export PGPASSWORD
# Снимок пишется во временное имя: недоснятый файл не должен выглядеть готовым.
docker exec -i -e PGPASSWORD "$MRANKED_DB_CONTAINER" \
  nice -n 10 pg_dump -h 127.0.0.1 -U "$BACKUP_DB_USER" -d "$BACKUP_DATABASE" \
  -Fc --no-password | python3 "$script_dir/backup-stream.py" \
    "$partial" "$BACKUP_MAX_DUMP_BYTES" "$BACKUP_RESERVE_BYTES"

# Decode every archive member; TOC alone does not detect truncated payload.
# This is integrity verification, not an actual database restore.
image="$(docker inspect --format '{{.Image}}' "$MRANKED_DB_CONTAINER")"
docker run --rm --network none --memory 256m --cpus 0.5 \
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

echo "backup $target ($(numfmt --to=iec "$size")) in $(( $(date -u +%s) - started ))s; kept $(ls -1 "$BACKUP_DIR"/mranked-*.dump | wc -l)"
