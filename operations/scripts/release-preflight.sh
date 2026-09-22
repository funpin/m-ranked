#!/usr/bin/env bash
# Что этот релиз потребует на сервере сверх обычной выкатки.
#
# Запускается на своей машине до подключения к серверу:
#
#     operations/scripts/release-preflight.sh <sha, выкаченный сейчас>
#
# Печатает только дельту между выкаченным и текущим деревом: новые миграции,
# изменившиеся юниты и конфигурация nginx, изменившиеся lock-файлы и новые
# обязательные переменные окружения. Ничего не меняет и никуда не ходит.
set -Eeuo pipefail

deployed="${1:?укажите sha, выкаченный на прод сейчас}"
head_sha="$(git rev-parse --short HEAD)"
git rev-parse --verify --quiet "$deployed^{commit}" >/dev/null || {
  echo "коммит $deployed не найден: сначала git fetch" >&2
  exit 1
}

section() { printf '\n== %s ==\n' "$1"; }
changed() { git diff --name-only "$deployed..HEAD" -- "$@"; }

echo "Выкатка $deployed → $head_sha"

section "Миграции (применять до перезапуска API)"
migrations="$(changed db/migrations)"
if [ -n "$migrations" ]; then
  echo "$migrations"
  echo "Порядок: резервная копия → проверка восстановления → psql -f каждая по очереди."
else
  echo "нет"
fi

section "Переменные окружения и учётные данные"
# Обязательными считаются те, чтение которых не имеет значения по умолчанию.
if [ -n "$(changed api/security.py api/sessions.py api/config.py)" ]; then
  echo "Менялось чтение конфигурации — сверьте /etc/m-ranked/api.env и credentials."
  git diff "$deployed..HEAD" -- api/security.py api/sessions.py api/config.py \
    | grep -E '^\+.*(os\.environ|_environment_or_file|_int\(|_flag\()' \
    | sed -E 's/^\+\s*/  /' | sort -u
else
  echo "чтение конфигурации не менялось"
fi
collector_config_changes="$(changed collector_runtime/config.py collector_target/__main__.py operations/env)"
if [ -n "$collector_config_changes" ]; then
  echo "Менялась конфигурация коллекторов — сверьте collector-common.env, platform env и collector-watchdog.env:"
  echo "$collector_config_changes"
fi

section "Конфигурация nginx (нужен nginx -t и reload)"
nginx_changes="$(changed operations/nginx)"
[ -n "$nginx_changes" ] && echo "$nginx_changes" || echo "нет"

section "systemd (нужен daemon-reload)"
unit_changes="$(changed operations/systemd)"
[ -n "$unit_changes" ] && echo "$unit_changes" || echo "нет"

section "Зависимости Python (прод на 3.11, lock собран под 3.13)"
lock_changes="$(changed requirements)"
if [ -n "$lock_changes" ]; then
  echo "$lock_changes"
  echo "Ставить только изменившиеся пакеты и только по хешу из lock;"
  echo "пакет с колесом cp313 на прод не встанет — нужна сборка под 3.11."
else
  echo "нет"
fi

section "Фронтенд (нужна пересборка standalone)"
front_changes="$(changed frontend contracts)"
[ -n "$front_changes" ] && echo "$front_changes" | head -20 || echo "нет"

section "Итог"
printf 'Читать перед выкаткой: operations/runbooks/DEPLOY.md, раздел «Порядок выкатки».\n'
