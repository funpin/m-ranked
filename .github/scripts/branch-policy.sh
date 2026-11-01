#!/usr/bin/env bash
# Поток веток M-Ranked (AGENTS.md, «Ветки, PR и выпуск»):
#   <тип>/<задача>  →  develop  →  main  →  тег vГГГГ.М.N  →  выкатка
# Вход — переменные окружения из события pull_request. Запуск локально:
#   BASE_REF=develop HEAD_REF=fix/x HEAD_REPO=a/b BASE_REPO=a/b PR_TITLE='fix: x' \
#     bash .github/scripts/branch-policy.sh
set -Eeuo pipefail

: "${BASE_REF:?}" "${HEAD_REF:?}" "${HEAD_REPO:?}" "${BASE_REPO:?}" "${PR_TITLE:?}"

# dependabot/<экосистема>/<пакет> — обновления из .github/dependabot.yml.
TASK_BRANCH='^((feat|fix|perf|refactor|docs|test|ci|build|chore|deps|data|revert)/[a-z0-9][a-z0-9._-]*|dependabot/[A-Za-z0-9._/-]+)$'
TASK_TITLE='^(feat|fix|perf|refactor|docs|test|ci|build|chore|deps|data|revert)(\([a-z0-9._/-]+\))?!?: .+'
RELEASE_TITLE='^release: v20[0-9]{2}\.(1[0-2]|[1-9])\.(0|[1-9][0-9]*)$'

fail() { echo "::error::$1" >&2; exit 1; }

case "$BASE_REF" in
  develop)
    [[ "$HEAD_REF" =~ $TASK_BRANCH ]] || fail \
      "В develop принимаются только ветки задач <тип>/<имя>: $TASK_BRANCH (получено: $HEAD_REF)"
    [[ "$PR_TITLE" =~ $TASK_TITLE ]] || fail \
      "Заголовок PR — Conventional Commits, «тип(область): что и зачем» (получено: $PR_TITLE)"
    ;;
  main)
    [[ "$HEAD_REF" == develop && "$HEAD_REPO" == "$BASE_REPO" ]] || fail \
      "В main сливается только develop этого репозитория (получено: $HEAD_REPO:$HEAD_REF)"
    [[ "$PR_TITLE" =~ $RELEASE_TITLE ]] || fail \
      "Заголовок выпускного PR — «release: vГГГГ.М.N», например «release: v2026.11.0» (получено: $PR_TITLE)"
    ;;
  *)
    fail "PR открываются только в develop (задачи) или main (выпуск из develop), а не в $BASE_REF"
    ;;
esac
echo "ok: $HEAD_REF → $BASE_REF"
