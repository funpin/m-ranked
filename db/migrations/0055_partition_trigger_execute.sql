-- 0055 — новые партиции замеров снова создаются
--
-- Партиция ingest.publication_metric_snapshot наследует триггеры родителя,
-- а для триггера нужно право EXECUTE на его функцию у владельца таблицы.
-- analytics.track_publication_latest (0020) принадлежит mranked_bootstrap и
-- разрешена только collector_ingest и maintenance; владелец таблицы —
-- migration_owner, поэтому ensure_publication_metric_partition (SECURITY
-- DEFINER от migration_owner) падала на партиции 2026_12 с «permission denied
-- for function», и почасовое обслуживание Сервера 2 завершалось ошибкой.
--
-- Применять от владельца функции (mranked_bootstrap), а не SET ROLE
-- migration_owner: выдать право может только владелец.
--
-- Откат: REVOKE EXECUTE ON FUNCTION analytics.track_publication_latest() FROM migration_owner;
BEGIN;
GRANT EXECUTE ON FUNCTION analytics.track_publication_latest() TO migration_owner;
COMMIT;
