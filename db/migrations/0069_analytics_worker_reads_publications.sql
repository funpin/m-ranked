-- 0069 — анализ аномалий читает дату публикации в оконных функциях.
--
-- Оконные функции точек (0068) берут месяц поста из ingest.publication:
-- горячая точка ищется в партиции этого месяца. Встроенные, они выполняются
-- с правами вызывающего, а analytics_worker читал публикации только через
-- ingest.visible_publication — 06.10 воркер анализа получил «permission
-- denied for table publication». У api_read, collector_ingest и maintenance
-- право есть.
--
-- Откат: REVOKE SELECT ON ingest.publication FROM analytics_worker.
BEGIN;
SET LOCAL lock_timeout = '5s';

GRANT SELECT ON ingest.publication TO analytics_worker;

COMMIT;
