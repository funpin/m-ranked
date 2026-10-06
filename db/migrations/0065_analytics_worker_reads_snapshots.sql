-- 0065 — анализ аномалий читает упакованную историю.
--
-- ingest.unpack_history (0059) — SQL-функция без SECURITY DEFINER: так она
-- встраивается в запрос и декодирует только нужный отрезок массивов. Но
-- встроенная, она выполняется с правами вызывающего, а видимость упакованной
-- точки с поздними строками сверяется с горячей таблицей снимков. У api_read
-- и collector_ingest право на неё было, у analytics_worker — нет: 06.10
-- сразу после выкатки воркер анализа падал на publication_point_at с
-- «permission denied for table publication_metric_snapshot».
--
-- Тех же данных роль и так видит всё — через представление точек; право
-- на таблицу их не расширяет.
--
-- Откат: REVOKE SELECT ON ingest.publication_metric_snapshot FROM analytics_worker.
BEGIN;
SET LOCAL lock_timeout = '5s';

GRANT SELECT ON ingest.publication_metric_snapshot TO analytics_worker;

COMMIT;
