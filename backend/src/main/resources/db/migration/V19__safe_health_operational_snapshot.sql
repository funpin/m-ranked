-- Public health sees only this bounded, sanitized operational projection.
-- It never receives arbitrary checkpoint values, source evidence, run IDs or error messages.
CREATE INDEX collection_run_health_latest_idx ON ingest.collection_run(platform, started_at DESC, id DESC)
    WHERE collector_version NOT LIKE 'sqlite-bridge/%';
CREATE INDEX collection_run_health_completed_idx ON ingest.collection_run(platform, completed_at DESC, id DESC)
    WHERE collector_version NOT LIKE 'sqlite-bridge/%' AND completed_at IS NOT NULL;
CREATE INDEX operational_checkpoint_health_idx ON ops_and_admin.operational_checkpoint(checkpoint_key, source_observed_at DESC, updated_at DESC)
    WHERE scope_type IN ('system','platform');

CREATE FUNCTION ops_and_admin.public_health_snapshot()
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog
SET statement_timeout = '3s'
AS $function$
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
), required(name) AS (VALUES ('publication_latest'),('publication_hourly'),('institution_daily_metrics'),
    ('institution_monthly_metrics'),('institution_period_metrics'),('comparison'),('publication_history'),
    ('publication_content'),('legacy_exports')),
published AS (
    SELECT dataset_revision_id FROM analytics.projection_state s
    WHERE s.status='ready' AND s.projection_name IN (SELECT name FROM required)
    GROUP BY dataset_revision_id HAVING count(*)=(SELECT count(*) FROM required)
    ORDER BY dataset_revision_id DESC LIMIT 1
)
SELECT jsonb_build_object(
    'asOf',statement_timestamp(),
    'channels',(SELECT count(*) FROM catalog.platform_account WHERE platform='telegram' AND enabled),
    'checkpoints',(SELECT jsonb_object_agg(key,value) FROM checkpoints),
    'runs',(SELECT jsonb_object_agg(platform,value) FROM run_states),
    'rawRevision',coalesce((SELECT max(id) FROM analytics.dataset_revision),0),
    'publishedRevision',coalesce((SELECT dataset_revision_id FROM published),0)
)
$function$;
REVOKE ALL ON FUNCTION ops_and_admin.public_health_snapshot() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.public_health_snapshot() TO api_read,maintenance;
REVOKE SELECT ON ops_and_admin.operational_checkpoint FROM api_read;
COMMENT ON FUNCTION ops_and_admin.public_health_snapshot() IS
    'Public safe operational fields only. Migration bridge runs never fabricate collector freshness. No raw history or arbitrary checkpoint access.';
