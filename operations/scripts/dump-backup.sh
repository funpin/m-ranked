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
# Три копии по гигабайту — потолок, при котором диск на боевой машине
# остаётся с запасом: полный диск останавливает саму базу.
: "${BACKUP_KEEP:=3}"
: "${MRANKED_DB_CONTAINER:?MRANKED_DB_CONTAINER is required}"

if [[ ! "$BACKUP_KEEP" =~ ^[0-9]+$ ]] || (( BACKUP_KEEP < 1 || BACKUP_KEEP > 90 )); then
  echo "BACKUP_KEEP must be between 1 and 90" >&2
  exit 64
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

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
  -Fc --no-password > "$partial"

# Проверка: оглавление читается, значит файл не оборван и заголовок цел.
#
# Формат с оглавлением требует файла, по которому можно перемещаться, поэтому
# поток через стандартный ввод здесь не годится. Если клиента на хосте нет,
# проверку делает разовый контейнер того же образа, что и сама база, — так
# версия клиента заведомо совпадает с версией формата.
if ! command -v pg_restore > /dev/null 2>&1 || ! pg_restore --list "$partial" > /dev/null 2>&1; then
  image="$(docker inspect --format '{{.Config.Image}}' "$MRANKED_DB_CONTAINER")"
  if ! docker run --rm -v "$BACKUP_DIR:/backups:ro" "$image" \
       pg_restore --list "/backups/$(basename "$partial")" > /dev/null; then
    echo "dump failed verification, keeping it as $partial" >&2
    exit 65
  fi
fi

mv -f "$partial" "$target"
size=$(stat -c %s "$target")
if (( size < 1048576 )); then
  echo "dump looks too small: $size bytes" >&2
  exit 65
fi

# Ротация: на диске остаётся ровно BACKUP_KEEP последних снимков.
ls -1t "$BACKUP_DIR"/mranked-*.dump 2>/dev/null | tail -n +$(( BACKUP_KEEP + 1 )) | xargs -r rm -f

echo "backup $target ($(numfmt --to=iec "$size")) in $(( $(date -u +%s) - started ))s; kept $(ls -1 "$BACKUP_DIR"/mranked-*.dump | wc -l)"
