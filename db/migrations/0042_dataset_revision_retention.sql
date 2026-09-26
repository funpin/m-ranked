-- 0042 — удалять старые ревизии набора данных
--
-- Причина: приёмник фиксирует ревизию на каждую принятую пачку — ~57 тысяч
-- строк в сутки, 348 МБ за 17 суток, и никто их не удаляет. Ревизия нужна,
-- пока на неё ссылается хоть одна таблица (витрины, последний замер,
-- очередь сброса кэша) или пока ею может закончиться курсор страницы.
--
-- Функция удаляет порцию ревизий старше окна, на которые не ссылается ни одна
-- таблица, и никогда — последнюю. Проверка ссылок идёт явно по каждой
-- ссылающейся таблице (NOT EXISTS), а не полагается на ошибку внешнего ключа:
-- одна ссылка иначе срывала бы всю порцию. Индексы по ссылающимся столбцам —
-- в operations/sql/storage-indexes.sql (CONCURRENTLY, до включения задачи):
-- без них проверка внешнего ключа при удалении просматривала бы таблицу
-- целиком на каждую строку.
--
-- Курсор страницы старше окна после удаления перестанет приниматься — это
-- та же ошибка «данные обновились», что и при обычной смене ревизии.
CREATE OR REPLACE FUNCTION ops_and_admin.purge_old_dataset_revisions(
 p_older_than interval DEFAULT interval '7 days', p_batch_size integer DEFAULT 1000)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','analytics','ops_and_admin','rating'
SET lock_timeout TO '1s'
AS $$
DECLARE deleted bigint;
BEGIN
 IF p_batch_size IS NULL OR p_batch_size NOT BETWEEN 1 AND 20000
    OR p_older_than IS NULL OR p_older_than < interval '2 days' THEN
   RAISE EXCEPTION 'unsafe revision purge bounds' USING ERRCODE='22023';
 END IF;
 WITH doomed AS (
   SELECT r.id FROM analytics.dataset_revision r
    WHERE r.committed_at < now() - p_older_than
      AND r.id < (SELECT max(id) FROM analytics.dataset_revision)
      AND NOT EXISTS (SELECT 1 FROM analytics.account_latest x WHERE x.dataset_revision_id = r.id)
      AND NOT EXISTS (SELECT 1 FROM analytics.anomaly_event x WHERE x.dataset_revision_id = r.id)
      AND NOT EXISTS (SELECT 1 FROM analytics.anomaly_source_revision x WHERE x.dataset_revision_id = r.id)
      AND NOT EXISTS (SELECT 1 FROM analytics.comparison_cohort x WHERE x.dataset_revision_id = r.id)
      AND NOT EXISTS (SELECT 1 FROM analytics.institution_daily_metrics x WHERE x.dataset_revision_id = r.id)
      AND NOT EXISTS (SELECT 1 FROM analytics.institution_metric_aggregate x WHERE x.dataset_revision_id = r.id)
      AND NOT EXISTS (SELECT 1 FROM analytics.institution_monthly_metrics x WHERE x.dataset_revision_id = r.id)
      AND NOT EXISTS (SELECT 1 FROM analytics.institution_period_metrics x WHERE x.dataset_revision_id = r.id)
      AND NOT EXISTS (SELECT 1 FROM analytics.legacy_overview_account x WHERE x.dataset_revision_id = r.id)
      AND NOT EXISTS (SELECT 1 FROM analytics.legacy_overview_card x WHERE x.dataset_revision_id = r.id)
      AND NOT EXISTS (SELECT 1 FROM analytics.publication_analysis_attempt x WHERE x.source_dataset_revision_id = r.id)
      AND NOT EXISTS (SELECT 1 FROM analytics.publication_analysis_state x WHERE x.source_dataset_revision_id = r.id)
      AND NOT EXISTS (SELECT 1 FROM analytics.publication_content x WHERE x.dataset_revision_id = r.id)
      AND NOT EXISTS (SELECT 1 FROM analytics.publication_history x WHERE x.dataset_revision_id = r.id)
      AND NOT EXISTS (SELECT 1 FROM analytics.publication_latest x WHERE x.dataset_revision_id = r.id)
      AND NOT EXISTS (SELECT 1 FROM ops_and_admin.outbox_event x WHERE x.dataset_revision_id = r.id)
      AND NOT EXISTS (SELECT 1 FROM rating.rating_run x WHERE x.dataset_revision_id = r.id)
    ORDER BY r.id
    LIMIT p_batch_size
    FOR UPDATE OF r SKIP LOCKED
 )
 DELETE FROM analytics.dataset_revision r USING doomed d WHERE r.id = d.id;
 GET DIAGNOSTICS deleted = ROW_COUNT;
 RETURN deleted;
END $$;
REVOKE ALL ON FUNCTION ops_and_admin.purge_old_dataset_revisions(interval,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.purge_old_dataset_revisions(interval,integer) TO maintenance;
