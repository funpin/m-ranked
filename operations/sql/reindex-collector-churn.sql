-- Еженедельная перестройка индексов сборщика на Сервере 1 (база сбора).
-- REINDEX CONCURRENTLY не держит долгих блокировок; вне транзакции.
-- Запускает m-ranked-target-reindex.service с MRANKED_REINDEX_SQL этого файла.
--
-- Каждый успешный опрос публикации переписывает её строку состояния
-- доступности с новыми last_checked_at и last_collection_run_id, а рабочий
-- набор сборщика каждый день сдвигает observed_at. Оба ключа проиндексированы,
-- так что обновления не HOT, а пустеющие страницы индекс назад не отдаёт.
-- На 01.11.2026: у ingest.publication_availability_state 21 МБ строк
-- (84 тыс.) и 566 МБ двух индексов, у рабочего набора 415 МБ строк и 568 МБ
-- индексов. В контейнер базы на 512 МБ это не помещается: она дочитывала с
-- диска по 14 МБ/с. Перестраиваются от меньшего к большему.
\set ON_ERROR_STOP off
SET lock_timeout = '10s';
SET statement_timeout = '30min';
REINDEX INDEX CONCURRENTLY ingest.collector_availability_run_ref_idx;
REINDEX INDEX CONCURRENTLY ingest.collector_availability_expiry_idx;
REINDEX INDEX CONCURRENTLY ingest.collector_publication_working_recent_idx;
REINDEX INDEX CONCURRENTLY ingest.collector_publication_working_set_pkey;
REINDEX INDEX CONCURRENTLY ingest.collector_publication_working_expiry_idx;

-- Прерванный REINDEX CONCURRENTLY оставляет нерабочую копию *_ccnew: служба
-- её только называет, удаляет оператор DROP INDEX CONCURRENTLY.
SELECT 'invalid index left: ' || i.indexrelid::regclass
  FROM pg_index i JOIN pg_namespace n ON n.oid = (SELECT relnamespace FROM pg_class WHERE oid = i.indexrelid)
 WHERE NOT i.indisvalid AND n.nspname IN ('ingest', 'analytics', 'ops_and_admin');
