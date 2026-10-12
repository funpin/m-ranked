#!/bin/bash
# Копия локальной БД для прогонов «до/после» (шаблон — восстановленный дамп).
# Прод не используется. usage: eval_setup.sh base|cand
set -euo pipefail
name="mranked_eval_$1"
psql_() { docker exec -i mranked-local-db psql -U mranked_bootstrap -X -v ON_ERROR_STOP=1 "$@"; }
psql_ -d postgres -c "DROP DATABASE IF EXISTS $name"
psql_ -d postgres -c "CREATE DATABASE $name TEMPLATE mranked_prod_20261008"
echo "created $name"
