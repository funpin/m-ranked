#!/usr/bin/env bash
# Диагностика Сервера 2 с машины оператора: mranked-doctor по SSH.
# Адрес и ключ в репозиторий не пишутся — их задаёт оператор:
#   export MRANKED_S2_SSH="-i ~/.ssh/<ключ> root@<адрес>"
#   operations/scripts/remote-doctor.sh --section units,backups
set -euo pipefail
: "${MRANKED_S2_SSH:?задайте MRANKED_S2_SSH: параметры ssh до Сервера 2}"
# shellcheck disable=SC2086 # параметры ssh намеренно разбиваются на слова
exec ssh $MRANKED_S2_SSH mranked-doctor "$@"
