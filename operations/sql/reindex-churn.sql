-- Еженедельная перестройка индексов с постоянной сменой ключей (0061).
-- REINDEX CONCURRENTLY не держит долгих блокировок; вне транзакции.
-- Запускает m-ranked-target-reindex.service от владельца схемы.
\set ON_ERROR_STOP off
SET lock_timeout = '10s';
SET statement_timeout = '30min';
REINDEX INDEX CONCURRENTLY analytics.publication_latest_account_idx;
REINDEX INDEX CONCURRENTLY analytics.publication_latest_revision_idx;
REINDEX INDEX CONCURRENTLY analytics.publication_latest_pkey;
REINDEX INDEX CONCURRENTLY ops_and_admin.outbox_event_dataset_revision_id_event_type_aggregate_type__key;
REINDEX INDEX CONCURRENTLY ops_and_admin.outbox_event_class_pending_idx;
REINDEX INDEX CONCURRENTLY ops_and_admin.outbox_event_pkey;
REINDEX INDEX CONCURRENTLY ops_and_admin.outbox_event_delivered_gc_idx;
REINDEX INDEX CONCURRENTLY ops_and_admin.outbox_event_pending_idx;
REINDEX INDEX CONCURRENTLY analytics.dataset_revision_committed_idx;
REINDEX INDEX CONCURRENTLY analytics.dataset_revision_pkey;

-- Горячий слой замеров и разбивки реакций (0059, 0071): строка живёт в
-- месячной партиции 48–72 часа, потом упаковщик её удаляет. Ключи индексов
-- всё время приходят и уходят, а пустые страницы индекс назад не отдаёт: на
-- 09.10 у сентябрьской партиции 4,6 ГБ индексов на 1,4 млн живых строк —
-- наследство 12,5 млн строк до упаковки, у октябрьской на столько же строк
-- 0,6 ГБ. Раздутый индекс ещё и не помещается в память, и каждое чтение
-- истории поста идёт на диск. Перестраиваются все индексы партиций крупнее
-- 8 МБ, от меньшего к большему: освобождённое меньшими место достаётся
-- следующим. Сколько места нужно самому крупному, заранее проверяет
-- reindex-churn.sh. BRIN не трогаем — он и так крошечный.
SELECT format('REINDEX INDEX CONCURRENTLY %s', i.indexrelid::regclass)
  FROM pg_inherits h
  JOIN pg_index i ON i.indrelid = h.inhrelid
  JOIN pg_class ic ON ic.oid = i.indexrelid
  JOIN pg_am am ON am.oid = ic.relam
 WHERE h.inhparent IN ('ingest.publication_metric_snapshot'::regclass, 'ingest.reaction_breakdown'::regclass)
   AND am.amname = 'btree' AND i.indisvalid
   AND pg_relation_size(i.indexrelid) > 8 * 1024 * 1024
 ORDER BY pg_relation_size(i.indexrelid)
\gexec

-- Прерванный REINDEX CONCURRENTLY оставляет нерабочую копию *_ccnew: она
-- занимает место и замедляет запись. Сама служба её не удаляет — только
-- называет, чтобы оператор проверил и удалил DROP INDEX CONCURRENTLY.
SELECT 'invalid index left: ' || i.indexrelid::regclass
  FROM pg_index i JOIN pg_namespace n ON n.oid = (SELECT relnamespace FROM pg_class WHERE oid = i.indexrelid)
 WHERE NOT i.indisvalid AND n.nspname IN ('ingest', 'analytics', 'ops_and_admin');
