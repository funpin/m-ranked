-- 0061 — часто обновляемые таблицы не пухнут.
--
-- analytics.publication_latest обновляется на каждом замере (7,25 млн
-- обновлений к октябрю) и ни разу не обновлялась на месте (HOT): observed_at
-- входит в индексы, и каждое обновление добавляет записи во все индексы.
-- Индекс (institution_id, platform, observed_at) за всё время использован
-- один раз и ни одним запросом не нужен — 93 МБ и лишняя запись на каждое
-- обновление. Удаляется.
--
-- Запас места на страницах (fillfactor) даёт обновлению остаться на той же
-- странице, а частая автоочистка — переиспользовать место до того, как
-- таблица вырастет: post_anomaly_state держала 441 МБ ради ~100 МБ данных.
-- Индексы с постоянной сменой ключей перестраивает еженедельная служба
-- m-ranked-target-reindex (REINDEX CONCURRENTLY, без долгих блокировок).
--
-- Откат: CREATE INDEX CONCURRENTLY publication_latest_institution_platform_idx
-- (0010) и ALTER TABLE … RESET (fillfactor, autovacuum_*).
BEGIN;
SET LOCAL lock_timeout = '5s';

DROP INDEX IF EXISTS analytics.publication_latest_institution_platform_idx;

ALTER TABLE analytics.publication_latest
    SET (fillfactor = 80, autovacuum_vacuum_scale_factor = 0.02, autovacuum_analyze_scale_factor = 0.05);
ALTER TABLE analytics.post_anomaly_state
    SET (fillfactor = 80, autovacuum_vacuum_scale_factor = 0.02, autovacuum_analyze_scale_factor = 0.05);
ALTER TABLE ingest.publication_availability_state
    SET (autovacuum_vacuum_scale_factor = 0.02);
ALTER TABLE ops_and_admin.outbox_event
    SET (autovacuum_vacuum_scale_factor = 0.02);
ALTER TABLE analytics.dataset_revision
    SET (autovacuum_vacuum_scale_factor = 0.05);

COMMIT;
