-- Одноразовая чистка постов, вышедших до 2026-07-01.
--
-- Наблюдение ведётся с первых минут поста; такие посты сборщик подхватывал
-- по ошибке (закреплённые записи, старые посты в ленте): замеров у них нет,
-- а на сайте они висели пустыми карточками. Новые такие не берутся — правило
-- первого обнаружения в collector_target/repository.py.
--
-- Одна транзакция. Каскадом уходят последнее значение, доступность,
-- идентичности, готовые страницы истории и прочее с ON DELETE CASCADE; без
-- каскада — удаляются явно. Если у этих постов окажутся замеры, скрипт
-- останавливается: замеры молча не удаляются.
--
-- Журнал проверок доступности — только для добавления (триггер
-- availability_event_immutable). Его строки этих постов удаляет владелец
-- таблицы: триггер выключается и включается в той же транзакции, запись в
-- журнал на эти секунды ждёт блокировки. 06.10 на проде таких строк было
-- 14 450, и без этого каскад останавливал чистку.
--
--   docker exec -i mranked-target-postgres-1 psql -U postgres -d mranked -v ON_ERROR_STOP=1 \
--     < operations/sql/purge-publications-before-2026-07.sql
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '15min';
SET LOCAL ROLE migration_owner;

CREATE TEMP TABLE doomed ON COMMIT DROP AS
SELECT id FROM ingest.publication WHERE published_at < DATE '2026-07-01';
ALTER TABLE doomed ADD PRIMARY KEY (id);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM ingest.publication_metric_snapshot WHERE publication_id IN (SELECT id FROM doomed))
       OR EXISTS (SELECT 1 FROM ingest.publication_metric_history WHERE publication_id IN (SELECT id FROM doomed)) THEN
        RAISE EXCEPTION 'posts before 2026-07 have measurements: purge stopped';
    END IF;
END $$;

-- Таблицы без ON DELETE CASCADE находятся по внешним ключам на публикацию:
-- список не устаревает вместе со схемой.
DO $$
DECLARE ref record;
BEGIN
    FOR ref IN
        SELECT c.conrelid::regclass AS relation, a.attname AS column_name
          FROM pg_constraint c
          JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
         WHERE c.contype = 'f' AND c.confrelid = 'ingest.publication'::regclass
           AND c.confdeltype <> 'c' AND c.conparentid = 0
           AND c.conrelid <> 'ingest.publication_metric_snapshot'::regclass
    LOOP
        EXECUTE format('DELETE FROM %s WHERE %I IN (SELECT id FROM doomed)', ref.relation, ref.column_name);
    END LOOP;
END $$;
ALTER TABLE ingest.publication_availability_event DISABLE TRIGGER availability_event_immutable;
DELETE FROM ingest.publication_availability_event WHERE publication_id IN (SELECT id FROM doomed);
ALTER TABLE ingest.publication_availability_event ENABLE TRIGGER availability_event_immutable;
-- Короткие адреса постов (/platform-posts/N) ведут на удалённое.
DELETE FROM catalog.legacy_entity_alias WHERE target_uuid IN (SELECT id FROM doomed);
DELETE FROM ingest.publication WHERE id IN (SELECT id FROM doomed);

SELECT count(*) AS purged FROM doomed;
COMMIT;
