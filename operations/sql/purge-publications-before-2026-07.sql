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
--   docker exec -i mranked-target-postgres-1 psql -U postgres -d mranked -v ON_ERROR_STOP=1 \
--     < operations/sql/purge-publications-before-2026-07.sql
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '15min';

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

DELETE FROM ops_and_admin.anomaly_analysis_candidate WHERE publication_id IN (SELECT id FROM doomed);
DELETE FROM analytics.post_anomaly_log WHERE publication_id IN (SELECT id FROM doomed);
DELETE FROM analytics.post_anomaly_state WHERE publication_id IN (SELECT id FROM doomed);
DELETE FROM analytics.publication_anomaly_review WHERE publication_id IN (SELECT id FROM doomed);
DELETE FROM analytics.publication_anomaly_finding WHERE publication_id IN (SELECT id FROM doomed);
DELETE FROM analytics.publication_analysis_attempt WHERE publication_id IN (SELECT id FROM doomed);
DELETE FROM analytics.publication_analysis_state WHERE publication_id IN (SELECT id FROM doomed);
DELETE FROM analytics.comparison_cohort_member WHERE publication_id IN (SELECT id FROM doomed);
DELETE FROM analytics.anomaly_event WHERE publication_id IN (SELECT id FROM doomed);
DELETE FROM analytics.anomaly_analysis_revision WHERE publication_id IN (SELECT id FROM doomed);
DELETE FROM ingest.deletion_observation WHERE publication_id IN (SELECT id FROM doomed);
DO $$
BEGIN
    IF to_regclass('ingest.collector_publication_working_set') IS NOT NULL THEN
        DELETE FROM ingest.collector_publication_working_set WHERE publication_id IN (SELECT id FROM doomed);
    END IF;
END $$;
-- Короткие адреса постов (/platform-posts/N) ведут на удалённое.
DELETE FROM catalog.legacy_entity_alias WHERE target_uuid IN (SELECT id FROM doomed);
DELETE FROM ingest.publication WHERE id IN (SELECT id FROM doomed);

SELECT count(*) AS purged FROM doomed;
COMMIT;
