-- Фаза A: добавление объектов. Выполняется при работающем старом коде.
--
-- Ничего не удаляет и не переписывает данные. Старый Java-API продолжает
-- читать проекции, коллекторы продолжают писать. Контракт схемы НЕ меняется:
-- старые коллекторы сверяют его на старте и отказались бы работать.
--
-- Обратимость: каждый объект снимается DROP'ом, см. delta-rollback-A.sql.
\set ON_ERROR_STOP on
BEGIN;

-- Барьер публикации. Прежняя latest_fully_published_dataset_revision()
-- возвращала последнюю ревизию, у которой все семь проекций имеют статус
-- ready, и потому свежие данные не показывались до прогона publisher.
CREATE FUNCTION analytics.latest_dataset_revision()
    RETURNS TABLE(id bigint, committed_at timestamp with time zone)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'analytics'
    AS $$
SELECT revision.id, revision.committed_at
  FROM analytics.dataset_revision revision
 ORDER BY revision.id DESC
 LIMIT 1
$$;
REVOKE ALL ON FUNCTION analytics.latest_dataset_revision() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analytics.latest_dataset_revision() TO api_read, api_write_admin, analytics_worker, maintenance;

-- Инвалидация кэша по факту записи вместо привязки ключа к номеру ревизии.
CREATE FUNCTION ops_and_admin.notify_cache_invalidation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'ops_and_admin'
    AS $$
BEGIN
    PERFORM pg_notify('mranked_cache', jsonb_build_object(
        'id', NEW.id, 'event', NEW.event_type, 'tags', to_jsonb(NEW.affected_tags))::text);
    RETURN NULL;
END
$$;
REVOKE ALL ON FUNCTION ops_and_admin.notify_cache_invalidation() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.notify_cache_invalidation() TO collector_ingest, api_write_admin, maintenance;

CREATE TRIGGER outbox_event_notify
    AFTER INSERT ON ops_and_admin.outbox_event
    FOR EACH ROW EXECUTE FUNCTION ops_and_admin.notify_cache_invalidation();

-- Очередь outbox не чистится ничем: на проде 78 МБ на 67 тысячах строк.
CREATE FUNCTION ops_and_admin.purge_delivered_outbox(p_older_than interval DEFAULT interval '1 day',
                                                     p_batch_size integer DEFAULT 10000)
    RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ops_and_admin'
    AS $$
DECLARE deleted bigint;
BEGIN
    IF p_batch_size < 1 OR p_batch_size > 100000 THEN
        RAISE EXCEPTION 'batch size out of range' USING ERRCODE='22023';
    END IF;
    WITH doomed AS (
        SELECT id FROM ops_and_admin.outbox_event
         WHERE (published_at IS NOT NULL AND published_at < now() - p_older_than)
            OR (terminal_at IS NOT NULL AND terminal_at < now() - p_older_than)
         ORDER BY id LIMIT p_batch_size FOR UPDATE SKIP LOCKED
    )
    DELETE FROM ops_and_admin.outbox_event victim USING doomed WHERE victim.id = doomed.id;
    GET DIAGNOSTICS deleted = ROW_COUNT;
    RETURN deleted;
END
$$;
REVOKE ALL ON FUNCTION ops_and_admin.purge_delivered_outbox(interval, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.purge_delivered_outbox(interval, integer) TO maintenance;

-- Роль чтения получает саму таблицу наблюдений. Прежде чтение шло через
-- представление _resolved и SECURITY DEFINER функцию; ни одна из обёрток не
-- скрывает строк, но LEFT JOIN к словарю тянет metric_evidence_id, которого
-- нет в индексе, и план вырождается из Index Only Scan в Index Scan.
GRANT SELECT ON TABLE ingest.publication_metric_snapshot TO api_read;
GRANT SELECT ON TABLE ingest.reaction_breakdown TO api_read;
GRANT SELECT ON TABLE ingest.account_metric_snapshot TO api_read;

-- Витрина последних значений переводится на обслуживание при записи.
-- Прежде её строил publisher целиком раз в час; на проде её observed_at
-- отстаёт от данных, потому что publisher остановлен. Семантика сохранена
-- дословно от rebuild_core_projections_v2: время и качество берутся из
-- последнего годного наблюдения, а каждая метрика — из последнего
-- наблюдения, где она не NULL.
CREATE FUNCTION analytics.track_publication_latest() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'analytics', 'ingest', 'catalog'
    AS $$
DECLARE
    account catalog.platform_account%ROWTYPE;
    owner_id uuid;
    completeness ingest.history_completeness;
BEGIN
    -- Синтетические и негодные наблюдения в витрину не попадают — ровно как в
    -- прежней пересборке.
    IF NEW.synthetic OR NEW.quality = 'invalid' THEN
        RETURN NULL;
    END IF;

    SELECT publication.primary_account_id, publication.history_completeness
      INTO owner_id, completeness
      FROM ingest.publication publication
     WHERE publication.id = NEW.publication_id;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    SELECT * INTO account FROM catalog.platform_account WHERE id = owner_id;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    INSERT INTO analytics.publication_latest AS current (
        publication_id, institution_id, platform_account_id, platform, observed_at,
        views_count, views_observed_at, views_quality,
        reactions_count, reactions_observed_at, reactions_quality,
        comments_count, comments_observed_at, comments_quality,
        shares_count, shares_observed_at, shares_quality,
        quality, interval_uncertain, synthetic, history_completeness,
        source_snapshot_refs, dataset_revision_id, refreshed_at
    ) VALUES (
        -- Тройка (count, observed_at, quality) по ограничению таблицы либо
        -- заполнена целиком, либо NULL целиком.
        NEW.publication_id, account.institution_id, account.id, account.platform, NEW.observed_at,
        NEW.views_count, CASE WHEN NEW.views_count IS NOT NULL THEN NEW.observed_at END,
        CASE WHEN NEW.views_count IS NOT NULL THEN NEW.views_quality END,
        NEW.reactions_count, CASE WHEN NEW.reactions_count IS NOT NULL THEN NEW.observed_at END,
        CASE WHEN NEW.reactions_count IS NOT NULL THEN NEW.reactions_quality END,
        NEW.comments_count, CASE WHEN NEW.comments_count IS NOT NULL THEN NEW.observed_at END,
        CASE WHEN NEW.comments_count IS NOT NULL THEN NEW.comments_quality END,
        NEW.shares_count, CASE WHEN NEW.shares_count IS NOT NULL THEN NEW.observed_at END,
        CASE WHEN NEW.shares_count IS NOT NULL THEN NEW.shares_quality END,
        NEW.quality, NEW.interval_uncertain, NEW.synthetic, completeness,
        jsonb_strip_nulls(jsonb_build_object(
            'latest', NEW.id,
            'views', CASE WHEN NEW.views_count IS NOT NULL THEN NEW.id END,
            'reactions', CASE WHEN NEW.reactions_count IS NOT NULL THEN NEW.id END,
            'comments', CASE WHEN NEW.comments_count IS NOT NULL THEN NEW.id END,
            'shares', CASE WHEN NEW.shares_count IS NOT NULL THEN NEW.id END)),
        (SELECT max(id) FROM analytics.dataset_revision), transaction_timestamp()
    )
    ON CONFLICT (publication_id) DO UPDATE SET
        observed_at = greatest(current.observed_at, EXCLUDED.observed_at),
        quality = CASE WHEN EXCLUDED.observed_at >= current.observed_at THEN EXCLUDED.quality ELSE current.quality END,
        interval_uncertain = CASE WHEN EXCLUDED.observed_at >= current.observed_at THEN EXCLUDED.interval_uncertain ELSE current.interval_uncertain END,
        synthetic = CASE WHEN EXCLUDED.observed_at >= current.observed_at THEN EXCLUDED.synthetic ELSE current.synthetic END,
        history_completeness = EXCLUDED.history_completeness,

        views_count = CASE WHEN EXCLUDED.views_observed_at IS NOT NULL
                            AND EXCLUDED.views_observed_at >= coalesce(current.views_observed_at, '-infinity')
                           THEN EXCLUDED.views_count ELSE current.views_count END,
        views_observed_at = greatest(current.views_observed_at, EXCLUDED.views_observed_at),
        views_quality = CASE WHEN EXCLUDED.views_observed_at IS NOT NULL
                              AND EXCLUDED.views_observed_at >= coalesce(current.views_observed_at, '-infinity')
                             THEN EXCLUDED.views_quality ELSE current.views_quality END,

        reactions_count = CASE WHEN EXCLUDED.reactions_observed_at IS NOT NULL
                                AND EXCLUDED.reactions_observed_at >= coalesce(current.reactions_observed_at, '-infinity')
                               THEN EXCLUDED.reactions_count ELSE current.reactions_count END,
        reactions_observed_at = greatest(current.reactions_observed_at, EXCLUDED.reactions_observed_at),
        reactions_quality = CASE WHEN EXCLUDED.reactions_observed_at IS NOT NULL
                                  AND EXCLUDED.reactions_observed_at >= coalesce(current.reactions_observed_at, '-infinity')
                                 THEN EXCLUDED.reactions_quality ELSE current.reactions_quality END,

        comments_count = CASE WHEN EXCLUDED.comments_observed_at IS NOT NULL
                               AND EXCLUDED.comments_observed_at >= coalesce(current.comments_observed_at, '-infinity')
                              THEN EXCLUDED.comments_count ELSE current.comments_count END,
        comments_observed_at = greatest(current.comments_observed_at, EXCLUDED.comments_observed_at),
        comments_quality = CASE WHEN EXCLUDED.comments_observed_at IS NOT NULL
                                 AND EXCLUDED.comments_observed_at >= coalesce(current.comments_observed_at, '-infinity')
                                THEN EXCLUDED.comments_quality ELSE current.comments_quality END,

        shares_count = CASE WHEN EXCLUDED.shares_observed_at IS NOT NULL
                             AND EXCLUDED.shares_observed_at >= coalesce(current.shares_observed_at, '-infinity')
                            THEN EXCLUDED.shares_count ELSE current.shares_count END,
        shares_observed_at = greatest(current.shares_observed_at, EXCLUDED.shares_observed_at),
        shares_quality = CASE WHEN EXCLUDED.shares_observed_at IS NOT NULL
                               AND EXCLUDED.shares_observed_at >= coalesce(current.shares_observed_at, '-infinity')
                              THEN EXCLUDED.shares_quality ELSE current.shares_quality END,

        source_snapshot_refs = jsonb_strip_nulls(current.source_snapshot_refs || EXCLUDED.source_snapshot_refs),
        dataset_revision_id = EXCLUDED.dataset_revision_id,
        refreshed_at = EXCLUDED.refreshed_at;

    RETURN NULL;
END
$$;

COMMENT ON FUNCTION analytics.track_publication_latest() IS
  'Поддерживает analytics.publication_latest при вставке наблюдения: последний снапшот задаёт время и качество, каждая метрика обновляется только более свежим не-NULL значением.';

CREATE TRIGGER publication_latest_track
    AFTER INSERT ON ingest.publication_metric_snapshot
    FOR EACH ROW EXECUTE FUNCTION analytics.track_publication_latest();

REVOKE ALL ON FUNCTION analytics.track_publication_latest() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analytics.track_publication_latest() TO collector_ingest, maintenance;

-- Снимок здоровья перестаёт ждать публикации проекций. Определение взято
-- с прода и правится точечно: прод новее снимка, с которого велась работа.
CREATE OR REPLACE FUNCTION ops_and_admin.public_health_snapshot()
 RETURNS jsonb
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog'
 SET statement_timeout TO '3s'
AS $function$;
WITH keys(key) AS (
    VALUES ('last_poll'),('next_poll'),('poll_last_started_at'),('poll_last_completed_at'),
      ('poll_last_duration_seconds'),('poll_last_error_count'),('poll_last_channel_count'),
      ('telegram_web_last_success_at'),('telegram_web_last_error'),
      ('vk_poll_last_completed_at'),('vk_poll_last_duration_seconds'),('vk_poll_last_error_count'),('vk_poll_last_account_count'),
      ('max_poll_last_completed_at'),('max_poll_last_duration_seconds'),('max_poll_last_error_count'),('max_poll_last_account_count'),
      ('rutube_poll_last_completed_at'),('rutube_poll_last_duration_seconds'),('rutube_poll_last_error_count'),('rutube_poll_last_account_count')
), checkpoints AS (
    SELECT keys.key, CASE
      WHEN c.value IS NULL OR c.value='null'::jsonb THEN 'null'::jsonb
      WHEN keys.key='telegram_web_last_error' THEN
        CASE WHEN c.value='""'::jsonb OR c.value='false'::jsonb OR c.value->'present'='false'::jsonb
             THEN 'null'::jsonb ELSE '"upstream_error"'::jsonb END
      WHEN keys.key ~ '(count|seconds)$' AND c.value #>> '{}' ~ '^[0-9]{1,12}(\.[0-9]{1,6})?$' THEN to_jsonb(c.value #>> '{}')
      WHEN keys.key ~ '(_at|_poll)$' AND c.value #>> '{}' ~ '^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9:.+-]{5,30}Z?$' THEN c.value
      ELSE 'null'::jsonb END AS value
    FROM keys LEFT JOIN LATERAL (
      SELECT CASE WHEN jsonb_typeof(value)='object' AND value ? 'unparsed_text'
        THEN value->'unparsed_text' ELSE value END AS value
      FROM ops_and_admin.operational_checkpoint c
      WHERE c.checkpoint_key=keys.key AND c.scope_type IN ('system','platform')
      ORDER BY c.source_observed_at DESC NULLS LAST,c.updated_at DESC,c.id DESC LIMIT 1
    ) c ON true
), platforms(platform) AS (VALUES ('telegram'),('vk'),('max'),('rutube')),
run_states AS (
    SELECT p.platform, jsonb_build_object('started_at',started.started_at,'completed_at',r.completed_at,
      'duration_seconds',extract(epoch FROM r.completed_at-r.started_at),'status',r.status,
      'error_count',r.error_count,'account_count',r.account_count) AS value
    FROM platforms p LEFT JOIN LATERAL (
      SELECT started_at FROM ingest.collection_run r
      WHERE r.platform=p.platform::catalog.platform_code AND collector_version NOT LIKE 'sqlite-bridge/%'
      ORDER BY r.started_at DESC,r.id DESC LIMIT 1
    ) started ON true LEFT JOIN LATERAL (
      SELECT started_at,completed_at,status,error_count,account_count FROM ingest.collection_run r
      WHERE r.platform=p.platform::catalog.platform_code AND collector_version NOT LIKE 'sqlite-bridge/%' AND completed_at IS NOT NULL
      ORDER BY r.completed_at DESC,r.id DESC LIMIT 1
    ) r ON true
), published AS (
    -- Данные видны сразу после фиксации ревизии: материализованных проекций,
    -- которых нужно было дожидаться, больше нет.
    SELECT revision.id AS dataset_revision_id, revision.committed_at
      FROM analytics.dataset_revision AS revision
     ORDER BY revision.id DESC LIMIT 1
), outbox_class AS (
    SELECT 'cacheDelivery' AS class,
           count(*) FILTER (WHERE published_at IS NULL AND terminal_at IS NULL) AS pending,
           min(occurred_at) FILTER (WHERE published_at IS NULL AND terminal_at IS NULL) AS oldest_pending_at,
           max(publish_attempts) FILTER (WHERE published_at IS NULL AND terminal_at IS NULL) AS max_attempts,
           count(*) FILTER (WHERE terminal_at IS NOT NULL) AS terminal
      FROM ops_and_admin.outbox_event
     GROUP BY class
), outbox AS (
    SELECT jsonb_build_object(
        'classes', coalesce((SELECT jsonb_object_agg(class, jsonb_build_object(
            'pending', pending,
            'oldestPendingAt', oldest_pending_at,
            'maxAttempts', coalesce(max_attempts, 0),
            'terminal', terminal
        )) FROM outbox_class), '{}'::jsonb),
        'oldestDeliverableAt', (
            SELECT min(occurred_at)
              FROM ops_and_admin.outbox_event
             WHERE published_at IS NULL
               AND terminal_at IS NULL
        )
    ) AS value
), storage AS (
    SELECT current_sample.*,
           CASE WHEN previous_sample.observed_at IS NULL THEN NULL ELSE
             round((current_sample.database_size_bytes-previous_sample.database_size_bytes)::numeric
               * 86400 / nullif(extract(epoch FROM current_sample.observed_at-previous_sample.observed_at),0)) END
             AS growth_bytes_per_day,
           CASE WHEN previous_sample.observed_at IS NULL
                  OR current_sample.wal_bytes < previous_sample.wal_bytes THEN NULL ELSE
             round((current_sample.wal_bytes-previous_sample.wal_bytes)
               * 86400 / nullif(extract(epoch FROM current_sample.observed_at-previous_sample.observed_at),0)) END
             AS wal_bytes_per_day,
           CASE WHEN previous_sample.observed_at IS NULL
                  OR current_sample.temporary_bytes < previous_sample.temporary_bytes THEN NULL ELSE
             round((current_sample.temporary_bytes-previous_sample.temporary_bytes)::numeric
               * 86400 / nullif(extract(epoch FROM current_sample.observed_at-previous_sample.observed_at),0)) END
             AS temporary_bytes_per_day
      FROM LATERAL (
          SELECT * FROM ops_and_admin.storage_observation ORDER BY observed_at DESC LIMIT 1
      ) AS current_sample
      LEFT JOIN LATERAL (
          SELECT * FROM ops_and_admin.storage_observation
           WHERE observed_at < current_sample.observed_at ORDER BY observed_at DESC LIMIT 1
      ) AS previous_sample ON true
)
SELECT jsonb_build_object(
    'asOf',statement_timestamp(),
    'channels',(SELECT count(*) FROM catalog.platform_account WHERE platform='telegram' AND enabled),
    'checkpoints',(SELECT jsonb_object_agg(key,value) FROM checkpoints),
    'runs',(SELECT jsonb_object_agg(platform,value) FROM run_states),
    'rawRevision',coalesce((SELECT max(id) FROM analytics.dataset_revision),0),
    'publishedRevision',coalesce((SELECT dataset_revision_id FROM published),0),
    'publishedGenerationAgeSeconds',(
        SELECT greatest(0, extract(epoch FROM statement_timestamp()-committed_at))::bigint
          FROM published
    ),
    'revisionLag',greatest(0,
        coalesce((SELECT max(id) FROM analytics.dataset_revision),0)
        - coalesce((SELECT dataset_revision_id FROM published),0)),
    'outbox',(SELECT value FROM outbox),
    'storage',coalesce((SELECT jsonb_build_object(
        'sampledAt',observed_at,
        'databaseSizeBytes',database_size_bytes,
        'growthBytesPerDay',growth_bytes_per_day,
        'walBytesPerDay',wal_bytes_per_day,
        'temporaryBytesPerDay',temporary_bytes_per_day,
        'largestRelations',largest_relations,
        'rowEstimates',row_estimates
    ) FROM storage), '{}'::jsonb)
)
$function$;

COMMIT;
