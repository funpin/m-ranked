-- Фаза C: уборка после переключения кода.
--
-- Выполняется только когда новый код подтверждён в работе: до этого момента
-- проекции читает старый Java-API, и удалять их нельзя.
--
-- Освобождает около 2837 МБ и снимает ~99 КБ исходников функций пересборки.
\set ON_ERROR_STOP on
BEGIN;

-- Барьер по проекциям в этом триггере больше не имеет смысла: проекций нет,
-- данные отдаются живыми. Политику нельзя привязать к ревизии старее
-- последней зафиксированной — её данные уже отданы наружу.
CREATE OR REPLACE FUNCTION analytics.guard_legacy_period_policy() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'analytics'
    AS $function$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('analytics.legacy_period_policy',0));
    IF NEW.effective_from_revision<coalesce((SELECT max(id) FROM analytics.dataset_revision),0)
       OR NEW.effective_from_revision<=coalesce((SELECT max(effective_from_revision) FROM analytics.legacy_period_policy),0)
       OR NOT EXISTS(SELECT 1 FROM analytics.dataset_revision WHERE id=NEW.effective_from_revision AND cause='configuration') THEN
        RAISE EXCEPTION 'period policy requires a new unpublished configuration revision' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $function$;

-- Построчный триггер на самом горячем пути записи, обслуживавший словарь
-- evidence. Интернирование переносится в код коллектора.
DROP TRIGGER IF EXISTS zz_compact_metric_evidence ON ingest.publication_metric_snapshot;

-- Функции эпохи publisher. Ни одну из них не зовёт ни код, ни схема.
DROP FUNCTION IF EXISTS analytics.rebuild_core_projections(bigint);
DROP FUNCTION IF EXISTS analytics.rebuild_core_projections_v2(bigint);
DROP FUNCTION IF EXISTS analytics.rebuild_core_projections_v5(bigint);
DROP FUNCTION IF EXISTS analytics.rebuild_core_projections_v6(bigint);
DROP FUNCTION IF EXISTS analytics.rebuild_core_projections_v9(bigint);
DROP FUNCTION IF EXISTS analytics.rebuild_core_projections_v11(bigint);
DROP FUNCTION IF EXISTS analytics.rebuild_core_projections_v13(bigint);
DROP FUNCTION IF EXISTS analytics.rebuild_serving_projections(bigint);
DROP FUNCTION IF EXISTS analytics.latest_fully_published_dataset_revision();
DROP FUNCTION IF EXISTS analytics.refresh_publication_content(bigint);
DROP FUNCTION IF EXISTS ingest.compact_new_metric_evidence();
DROP FUNCTION IF EXISTS ingest.intern_metric_evidence(jsonb);
DROP FUNCTION IF EXISTS ops_and_admin.compact_metric_evidence_batch(date, bigint, integer);
DROP FUNCTION IF EXISTS ops_and_admin.drop_publication_metric_partition(date, uuid);

-- Мёртвый остаток эксперимента: в развёрнутом коде нет ни одного упоминания.
DROP FUNCTION IF EXISTS analytics.publication_latest_metrics(uuid, date, timestamptz);
DROP FUNCTION IF EXISTS analytics.publication_latest_metrics(uuid[], date, timestamptz);

-- Материализованные почасовые проекции. Чтение переведено на живые запросы
-- по ingest с обязательным предикатом published_month.
DROP TABLE IF EXISTS analytics.comparison_metric_point;
DROP TABLE IF EXISTS analytics.comparison_publication_hourly;
DROP TABLE IF EXISTS analytics.publication_hourly;
DROP TABLE IF EXISTS analytics.projection_state;

COMMIT;
