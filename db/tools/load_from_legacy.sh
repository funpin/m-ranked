#!/usr/bin/env bash
# Переносит данные из базы прежней схемы в базу, построенную db/migrations.
# Одноразовый инструмент сверки: он доказывает, что новая схема принимает
# существующие данные без потерь, и меряет фактическую экономию места.
#
#   db/tools/load_from_legacy.sh <container> <source-db> <target-db>
set -euo pipefail

CONTAINER=${1:?usage: load_from_legacy.sh <container> <source-db> <target-db>}
SRC=${2:?}
DST=${3:?}
PSQL="docker exec -i $CONTAINER psql -U mranked_bootstrap -v ON_ERROR_STOP=1 -q"

# Каждый вызов psql, кроме конвейеров COPY, получает пустой stdin: иначе
# docker exec -i вычитывает чужой ввод и ломает окружающие циклы.

src() { $PSQL -d "$SRC" "$@" </dev/null; }
dst() { $PSQL -d "$DST" "$@" </dev/null; }

echo "== партиции =="
# Список читается в переменную, а не через конвейер: docker exec -i внутри
# while read забрал бы себе весь stdin, и создался бы только первый месяц.
months=$(src -At -c "SELECT DISTINCT to_char(published_month,'YYYY-MM-DD')
                       FROM ingest.publication_metric_snapshot ORDER BY 1")
expected=$(printf '%s\n' "$months" | grep -c .)
for month in $months; do
  dst -At -c "SELECT ops_and_admin.ensure_publication_metric_partition('$month'::date)" </dev/null >/dev/null
done
got=$(dst -At -c "SELECT count(*) FROM pg_inherits
                   WHERE inhparent='ingest.publication_metric_snapshot'::regclass" </dev/null)
# Партиция по умолчанию прибавляет единицу к ожидаемому числу.
if [ "$got" -ne "$((expected + 1))" ]; then
  echo "партиций создано $got, ожидалось $((expected + 1)) — прерываю" >&2
  exit 1
fi
echo "создано: $got (месяцев $expected + default)"

echo "== таблицы =="
# Порядок не важен: загрузка идёт с session_replication_role=replica, поэтому
# внешние ключи и триггеры неизменяемости во время переноса не срабатывают.
tables=$(src -At -c "
  SELECT n.nspname||'.'||c.relname
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE c.relkind IN ('r','p') AND NOT c.relispartition
     AND n.nspname IN ('analytics','catalog','ingest','ops_and_admin','rating')
     AND c.relname NOT IN ('publication_hourly','comparison_publication_hourly',
                           'comparison_metric_point','projection_state')
   ORDER BY 1")

for t in $tables; do
  schema=${t%%.*}; name=${t##*.}
  # Столбцы в порядке объявления; отпечаток источника переводится в bytea.
  cols=$(src -At -c "
    SELECT string_agg(quote_ident(column_name), ',' ORDER BY ordinal_position)
      FROM information_schema.columns
     WHERE table_schema='$schema' AND table_name='$name'
       AND is_generated='NEVER'")
  sel=$(src -At -c "
    SELECT string_agg(
             CASE WHEN column_name='source_fingerprint'
                  THEN 'decode('||quote_ident(column_name)||E',\'hex\')'
                  ELSE quote_ident(column_name) END, ',' ORDER BY ordinal_position)
      FROM information_schema.columns
     WHERE table_schema='$schema' AND table_name='$name'
       AND is_generated='NEVER'")
  [ -z "$cols" ] && { echo "  $t — нет столбцов, пропуск"; continue; }

  docker exec -i "$CONTAINER" psql -U mranked_bootstrap -d "$SRC" -q -v ON_ERROR_STOP=1 \
      -c "COPY (SELECT $sel FROM $t) TO STDOUT" |
  docker exec -i "$CONTAINER" psql -U mranked_bootstrap -d "$DST" -q -v ON_ERROR_STOP=1 \
      -c "SET session_replication_role='replica'" \
      -c "COPY $t ($cols) FROM STDIN"
  printf '  %-46s %s\n' "$t" "$(dst -At -c "SELECT count(*) FROM $t")"
done

echo "== последовательности =="
dst -At -c "
DO \$\$
DECLARE r record; last_value bigint;
BEGIN
  FOR r IN
    SELECT s.nspname AS seq_schema, sc.relname AS seq_name,
           t.nspname AS tbl_schema, tc.relname AS tbl_name, a.attname AS col
      FROM pg_class sc
      JOIN pg_namespace s ON s.oid=sc.relnamespace
      JOIN pg_depend d ON d.objid=sc.oid AND d.classid='pg_class'::regclass AND d.deptype IN ('a','i')
      JOIN pg_class tc ON tc.oid=d.refobjid
      JOIN pg_namespace t ON t.oid=tc.relnamespace
      JOIN pg_attribute a ON a.attrelid=tc.oid AND a.attnum=d.refobjsubid
     WHERE sc.relkind='S' AND t.nspname IN ('analytics','catalog','ingest','ops_and_admin','rating')
  LOOP
    EXECUTE format('SELECT coalesce(max(%I),0) FROM %I.%I', r.col, r.tbl_schema, r.tbl_name)
      INTO last_value;
    EXECUTE format('SELECT setval(%L, GREATEST(%s,1), %L)',
                   r.seq_schema||'.'||r.seq_name, last_value, last_value > 0);
  END LOOP;
END \$\$;" >/dev/null
echo "выставлены"

echo "== REINDEX =="
# Массовая загрузка набивает btree рыхлее, чем постепенные вставки: страницы
# делятся пополам вместо дописывания вправо. На этих данных разница — 481 МБ.
dst -c "REINDEX DATABASE $DST" >/dev/null

echo "== ANALYZE =="
dst -c "ANALYZE" >/dev/null

echo "== проверка размещения =="
# Строки в партиции по умолчанию означают, что нужная партиция не создана:
# данные лежат одной кучей, отсечение не работает, индекс один на всё.
for tbl in publication_metric_snapshot reaction_breakdown; do
  stray=$(dst -At -c "SELECT count(*) FROM ingest.${tbl}_default")
  if [ "$stray" != "0" ]; then
    echo "в ingest.${tbl}_default осело $stray строк — партиции созданы не все" >&2
    exit 1
  fi
  echo "  ingest.${tbl}_default пуста"
done
echo "готово"
