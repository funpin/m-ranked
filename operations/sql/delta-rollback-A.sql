-- Откат фазы A. Снимает всё, что она добавила, и возвращает снимок здоровья
-- к барьеру по проекциям. Данные не затрагиваются.
\set ON_ERROR_STOP on
BEGIN;

DROP TRIGGER IF EXISTS publication_latest_track ON ingest.publication_metric_snapshot;
DROP FUNCTION IF EXISTS analytics.track_publication_latest();

DROP TRIGGER IF EXISTS outbox_event_notify ON ops_and_admin.outbox_event;
DROP FUNCTION IF EXISTS ops_and_admin.notify_cache_invalidation();

DROP FUNCTION IF EXISTS ops_and_admin.purge_delivered_outbox(interval, integer);
DROP FUNCTION IF EXISTS analytics.latest_dataset_revision();

REVOKE SELECT ON TABLE ingest.publication_metric_snapshot FROM api_read;
REVOKE SELECT ON TABLE ingest.reaction_breakdown FROM api_read;
REVOKE SELECT ON TABLE ingest.account_metric_snapshot FROM api_read;

-- Снимок здоровья возвращается к барьеру по проекциям. Определение снято
-- с прода до применения фазы A.
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
), required(name) AS (VALUES ('publication_latest'),('publication_hourly'),('publication_history'),('institution_daily_metrics'),
    ('institution_monthly_metrics'),('institution_period_metrics'),('comparison')),
published AS (
    SELECT s.dataset_revision_id, revision.committed_at
      FROM analytics.projection_state s
      JOIN analytics.dataset_revision AS revision
        ON revision.id = s.dataset_revision_id
    WHERE s.status='ready' AND s.projection_name IN (SELECT name FROM required)
    GROUP BY s.dataset_revision_id, revision.committed_at
    HAVING count(*)=(SELECT count(*) FROM required)
    ORDER BY s.dataset_revision_id DESC LIMIT 1
), outbox_class AS (
    SELECT CASE
             WHEN event_type = 'projection.rebuild.requested' THEN 'projectionControl'
             WHEN event_type = 'projection.published' THEN 'projectionLifecycle'
             ELSE 'cacheDelivery'
           END AS class,
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
               AND event_type <> 'projection.rebuild.requested'
               AND event_type <> 'projection.published'
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
