#!/usr/bin/env bash
# Выкатка выпуска на Сервер 2 (профиль B). Ставится вне релиза:
#   install -o root -g root -m 0755 operations/deploy/deploy-release.sh \
#     /usr/local/libexec/m-ranked/deploy-release
# Вызывается deploy-entrypoint (ключ GitHub Actions) через sudo или
# оператором вручную:
#   deploy-release deploy <vГГГГ.М.N> <sha256 архива> migrations=yes|no config=yes|no
#   deploy-release status
#
# Порядок — тот же, что в operations/runbooks/DEPLOY.md, только без ручных
# шагов: проверить всё, что можно проверить без изменений; затем миграции;
# затем атомарное переключение `current`, перезапуск и проверка; при отказе
# проверки — возврат прежнего `current`. Миграции назад не откатываются: они
# пишутся расширением схемы (expand), которое прежний код переносит.
#
# Без флагов скрипт ничего не применяет сверх кода: новые миграции и
# изменения юнитов/nginx/env останавливают выкатку до переключения.
set -Eeuo pipefail
umask 022

CONFIG=/etc/m-ranked/deploy.env
# shellcheck source=/dev/null
[[ -r "$CONFIG" ]] && . "$CONFIG"
: "${MRANKED_GITHUB_REPO:=funpin/m-ranked}"
: "${MRANKED_ROOT:=/opt/m-ranked}"
: "${MRANKED_STATE_DIR:=/var/lib/m-ranked/deploy}"
: "${MRANKED_PG_CONTAINER:=mranked-target-postgres-1}"
: "${MRANKED_PG_DATABASE:=mranked}"
: "${MRANKED_PG_SUPERUSER:=mranked_bootstrap}"
: "${MRANKED_API_URL:=http://127.0.0.1:18080}"
: "${MRANKED_WEB_URL:=http://127.0.0.1:3000}"
: "${MRANKED_BUILD_CONF:=/etc/m-ranked/nginx/build.conf}"
: "${MRANKED_BACKUP_DIR:=/var/backups/m-ranked}"
: "${MRANKED_BACKUP_MAX_AGE_HOURS:=26}"
: "${MRANKED_RELEASE_GROUP:=m-ranked-release-readers}"
: "${MRANKED_PYTHON:=/usr/bin/python3.13}"
# Долгоживущие службы, которые читают код из current. Таймеры подхватят
# новый current при следующем запуске сами. Невключённые пропускаются.
: "${MRANKED_RESTART_UNITS:=m-ranked-target-api m-ranked-target-web m-ranked-target-cache-warmup m-ranked-target-anomaly-analysis m-ranked-target-transfer-ingest m-ranked-target-telegram-bot}"

RELEASES="$MRANKED_ROOT/releases"
DEPLOYMENTS="$MRANKED_ROOT/deployments"
CURRENT="$MRANKED_ROOT/current"
LEDGER="$MRANKED_STATE_DIR/applied-migrations"
# Маркер идущей выкатки: агент основного сервера (operations/storage/main_agent.py)
# раз в минуту кладёт его в отчёт, и панель с ботом показывают «обновляется».
MARKER="$MRANKED_STATE_DIR/in-progress.json"
MARKED=""
DEPLOY_STARTED="$(date +%s)"
LOCK=/run/lock/m-ranked-release.lock
VERSION_RE='^v20[0-9]{2}\.(1[0-2]|[1-9])\.(0|[1-9][0-9]*)$'
LOCKS=(tooling api collector anomaly)
# Что сервер настраивает руками и что выкатка не ставит сама.
CONFIG_PATHS=(operations/systemd operations/nginx operations/env operations/tmpfiles.d operations/redis)

log() { printf '%s %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
die() { printf 'ОСТАНОВКА: %s\n' "$*" >&2; exit 1; }

status() {
  local target; target="$(readlink -f "$CURRENT")"
  echo "current: $target"
  [[ -f "$target/release.json" ]] && cat "$target/release.json"
  local last; last="$(ls -1t "$DEPLOYMENTS"/*/activation.json 2>/dev/null | head -1 || true)"
  [[ -n "$last" ]] && { echo "последняя выкатка: $last"; cat "$last"; }
  for unit in $MRANKED_RESTART_UNITS; do
    printf '%-44s %s\n' "$unit" "$(systemctl is-active "$unit" 2>/dev/null || true)"
  done
}

psql_admin() {
  docker exec -i "$MRANKED_PG_CONTAINER" psql -U "$MRANKED_PG_SUPERUSER" \
    -d "$MRANKED_PG_DATABASE" -X -v ON_ERROR_STOP=1
}

lock_digest() {  # отпечаток набора lock-файлов дерева
  local tree="$1" name
  for name in "${LOCKS[@]}"; do sha256sum "$tree/requirements/$name.lock"; done \
    | awk '{print $1}' | sha256sum | awk '{print $1}'
}

prepare_venv() {  # среда Python 3.13 нового дерева
  local tree="$1" current_tree="$2"
  if [[ -e "$current_tree/.venv/bin/python" ]] \
      && [[ "$(lock_digest "$tree")" == "$(lock_digest "$current_tree")" ]]; then
    # Зависимости те же: новый релиз делит среду с текущим, как и сейчас.
    ln -s "$(readlink -f "$current_tree/.venv")" "$tree/.venv"
    log "lock-файлы не менялись: среда $(readlink -f "$current_tree/.venv")"
    return
  fi
  log "lock-файлы изменились: новая среда в $tree/.venv"
  "$MRANKED_PYTHON" -m venv "$tree/.venv"
  "$tree/.venv/bin/pip" install --quiet --require-hashes --no-deps --upgrade \
    -r "$tree/requirements/tooling.lock"
  local name
  for name in api collector anomaly; do
    "$tree/.venv/bin/pip" install --quiet --require-hashes --no-deps --no-build-isolation \
      -r "$tree/requirements/$name.lock"
  done
  "$tree/.venv/bin/pip" check
}

new_migrations() {  # файлы выпуска, которых нет в журнале применённых
  local tree="$1" file
  for file in "$tree"/db/migrations/[0-9][0-9][0-9][0-9]_*.sql; do
    [[ -e "$file" ]] || continue
    grep -qxF "$(basename "$file")" "$LEDGER" || echo "$file"
  done
}

config_delta() {
  local from="$1" to="$2" path
  for path in "${CONFIG_PATHS[@]}"; do
    [[ -e "$from/$path" || -e "$to/$path" ]] || continue
    diff -rq "$from/$path" "$to/$path" 2>/dev/null | sed "s|$from/||; s|$to/||" || true
  done
}

wait_healthy() {
  local commit="$1" html
  for _ in $(seq 1 40); do
    # Страница — в переменную, а не в «curl | grep -q»: grep -q закрывает канал
    # на первом совпадении, curl получает EPIPE (код 23), и под pipefail
    # проверка проваливалась при верной странице. 01.11.2026 так был снят
    # исправный выпуск v2026.11.0.
    if curl -fsS --max-time 10 "$MRANKED_API_URL/api/v1/health/live" >/dev/null 2>&1 \
        && curl -fsS --max-time 10 "$MRANKED_API_URL/api/v1/health/ready" >/dev/null 2>&1 \
        && html="$(curl -fsS --max-time 20 "$MRANKED_WEB_URL/" 2>/dev/null)" \
        && [[ "$html" == *"dpl=$commit"* ]]; then
      return 0
    fi
    sleep 3
  done
  return 1
}

write_build_conf() {
  local tree="$1" commit="$2" build_id
  build_id="$(cat "$tree/frontend/.next/BUILD_ID")"
  [[ "$build_id" =~ ^[A-Za-z0-9_-]+$ ]] || die "странный BUILD_ID: $build_id"
  printf 'map $host $m_ranked_build {\n    default "%s-%s";\n}\n' "$build_id" "${commit:0:7}" \
    > "$MRANKED_BUILD_CONF.next"
  mv -f "$MRANKED_BUILD_CONF.next" "$MRANKED_BUILD_CONF"
}

restart_units() {
  local unit
  for unit in $MRANKED_RESTART_UNITS; do
    systemctl is-enabled --quiet "$unit" 2>/dev/null || { log "пропуск $unit (не включён)"; continue; }
    systemctl restart "$unit"
  done
}

switch_to() {  # атомарная замена симлинка current
  ln -sfn "$1" "$CURRENT.next" && mv -T "$CURRENT.next" "$CURRENT"
}

# Внутри «if ! activate» set -e не действует, поэтому каждый шаг проверен явно.
activate() {
  local target="$1" commit="$2"
  switch_to "$target" || return 1
  write_build_conf "$target" "$commit" || return 1
  { nginx -t -q && systemctl reload nginx; } || return 1
  restart_units || return 1
  wait_healthy "$commit"
}

mark() {  # шаг выкатки для панели; ошибка записи выкатку не останавливает
  jq -n --arg version "$1" --arg phase "$2" --argjson started "$DEPLOY_STARTED" \
    '{version: $version, phase: $phase, startedAt: $started}' > "$MARKER.next" 2>/dev/null \
    && mv -f "$MARKER.next" "$MARKER" && MARKED=1 || true
}

STAGING=""
trap '[[ -n "$STAGING" ]] && rm -rf -- "$STAGING"; [[ -n "$MARKED" ]] && rm -f -- "$MARKER"' EXIT

deploy() {
  local version="$1" digest="$2" migrations="$3" config="$4"
  [[ "$version" =~ $VERSION_RE ]] || die "версия '$version' не vГГГГ.М.N"
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || die "отпечаток не sha256"
  [[ "$migrations" == yes || "$migrations" == no ]] || die "migrations=yes|no"
  [[ "$config" == yes || "$config" == no ]] || die "config=yes|no"
  [[ -f "$LEDGER" ]] || die "нет журнала миграций $LEDGER (operations/deploy/README.md, «Один раз»)"

  install -d -m 0755 "$(dirname "$LOCK")"
  exec 9>"$LOCK"
  flock -n 9 || die "блокировку $LOCK держит другая выкатка или GC релизов"

  local name="mranked-$version-s2" previous target
  target="$RELEASES/$name"
  previous="$(readlink -f "$CURRENT")"
  [[ "$target" != "$previous" ]] || { log "$version уже выкачен"; status; return 0; }
  mark "$version" "подготовка"

  if [[ -d "$target" ]]; then
    # Повторная активация — откат на уже проверенный прежний выпуск.
    [[ "$(cat "$target/.release-sha256" 2>/dev/null)" == "$digest" ]] \
      || die "$target уже есть, но собран из другого архива"
    log "дерево $name уже на сервере: повторная активация"
  else
    STAGING="$(mktemp -d "$RELEASES/.staging-$version.XXXXXX")"
    log "загрузка $version"
    curl -fsSL --retry 3 --max-time 600 -o "$STAGING/release.tar.gz" \
      "https://github.com/$MRANKED_GITHUB_REPO/releases/download/$version/m-ranked-$version.tar.gz"
    echo "$digest  $STAGING/release.tar.gz" | sha256sum --check --strict --quiet \
      || die "архив не совпал с отпечатком из выпуска"
    install -d "$STAGING/tree"
    tar -xzf "$STAGING/release.tar.gz" -C "$STAGING/tree" --no-same-owner
    local tree="$STAGING/tree"
    [[ "$(jq -r .version "$tree/release.json")" == "$version" ]] || die "release.json не про $version"
    [[ -f "$tree/frontend/server.js" && -d "$tree/frontend/.next/static" ]] \
      || die "в архиве нет собранного сайта"
    install -d -m 0755 "$tree/frontend/.next/cache"   # точка монтирования кэша web
    prepare_venv "$tree" "$previous"
    (cd "$tree" && .venv/bin/python -c \
      'import api.app, anomaly_analysis.v2.worker, transfer_ingest') \
      || die "код выпуска не импортируется в своей среде"
    echo "$digest" > "$tree/.release-sha256"
    chown -R root:"$MRANKED_RELEASE_GROUP" "$tree"
    chmod 0750 "$tree"
    mv -T "$tree" "$target"
    rm -rf -- "$STAGING"; STAGING=""
  fi

  local commit; commit="$(jq -r .commit "$target/release.json")"

  # Конфигурация сервера настраивается руками (юниты с drop-in'ами, nginx).
  local delta; delta="$(config_delta "$previous" "$target")"
  if [[ -n "$delta" && "$config" != yes ]]; then
    printf '%s\n' "$delta" >&2
    die "выпуск меняет конфигурацию сервера (выше). Примените по DEPLOY.md и повторите с config_reviewed"
  fi

  # Миграции — до кода; ручные (-- deploy: manual) — только оператором.
  local pending=() file
  while IFS= read -r file; do [[ -n "$file" ]] && pending+=("$file"); done \
    < <(new_migrations "$target")
  if ((${#pending[@]})); then
    printf 'новые миграции: %s\n' "${pending[@]##*/}" >&2
    for file in "${pending[@]}"; do
      ! grep -qE '^-- deploy: manual' "$file" \
        || die "${file##*/} помечена «-- deploy: manual»: применяет оператор по DEPLOY.md, затем запись в $LEDGER"
    done
    [[ "$migrations" == yes ]] || die "выпуск несёт миграции (выше): повторите с apply_migrations после просмотра"
    local dump age
    dump="$(ls -1t "$MRANKED_BACKUP_DIR"/*.dump 2>/dev/null | head -1 || true)"
    [[ -n "$dump" ]] || die "нет дампа в $MRANKED_BACKUP_DIR: миграции без резервной копии не применяются"
    age=$(( ( $(date +%s) - $(stat -c %Y "$dump") ) / 3600 ))
    (( age <= MRANKED_BACKUP_MAX_AGE_HOURS )) \
      || die "последний дамп ${dump##*/} старше $MRANKED_BACKUP_MAX_AGE_HOURS ч ($age ч)"
    mark "$version" "миграции"
    for file in "${pending[@]}"; do
      log "миграция ${file##*/}"
      { echo "SET ROLE migration_owner;"; echo "SET lock_timeout = '10s';"; cat "$file"; } \
        | psql_admin >/dev/null
      echo "${file##*/}" >> "$LEDGER"
    done
  fi

  # Переключение. Прежний build.conf — для отката.
  local record="$DEPLOYMENTS/$version"
  install -d -m 0750 "$record"
  cp -p "$MRANKED_BUILD_CONF" "$record/build.conf.before"
  log "переключение $(basename "$previous") → $name"
  mark "$version" "переключение"
  if ! activate "$target" "$commit"; then
    log "проверка не прошла: возврат на $(basename "$previous")"
    mark "$version" "откат"
    switch_to "$previous"
    cp -p "$record/build.conf.before" "$MRANKED_BUILD_CONF"
    nginx -t -q && systemctl reload nginx
    restart_units
    die "$version не поднялся и снят; прод на $(basename "$previous")"
  fi

  jq -n --arg deployment "$version" --arg release "$target" --arg previous "$previous" \
    --arg commit "$commit" --arg digest "$digest" --arg at "$(date -Is)" \
    --arg config "$config" --args '{deployment: $deployment, release: $release,
      previous_release: $previous, commit: $commit, sha256: $digest, at: $at,
      config_reviewed: ($config == "yes"), migrations_applied: $ARGS.positional}' \
    "${pending[@]##*/}" > "$record/activation.json"
  log "$version выкачен; откат — выкатка прежнего выпуска ($(basename "$previous"))"
}

case "${1:-}" in
  status) status ;;
  deploy)
    [[ $# -eq 5 ]] || die "deploy <версия> <sha256> migrations=yes|no config=yes|no"
    deploy "$2" "$3" "${4#migrations=}" "${5#config=}"
    ;;
  *) die "команды: deploy, status" ;;
esac
