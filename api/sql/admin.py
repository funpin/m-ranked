"""Ограниченные административные чтения и вызовы атомарных команд."""
from __future__ import annotations


CATALOG = """
WITH page AS MATERIALIZED (
    SELECT institution.*,alias.legacy_id FROM catalog.visible_institution institution
    JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=institution.id
      AND alias.entity_type='institutions'
    WHERE alias.legacy_id>%(after)s ORDER BY alias.legacy_id LIMIT %(limit)s
), account_rows AS (
    SELECT account.institution_id,alias.legacy_id,
      row_number() OVER(PARTITION BY account.institution_id ORDER BY alias.legacy_id) AS ordinal,
      jsonb_build_object('id',account.id,'legacyId',alias.legacy_id,
        'channelId',channel.legacy_id,'institutionId',account.institution_id,
        'platform',account.platform,'externalKey',account.canonical_external_id,
        'username',account.current_username,'title',account.current_title,
        'url',account.current_url,'accessMode',account.access_mode,'enabled',account.enabled,
        'rowVersion',account.row_version,'nativeId',native.external_id,'subscribers',metric.value,
        'legacyAccessMode',presentation.access_mode,'lastErrorCode',presentation.last_error_code) AS item
    FROM page JOIN LATERAL (
      SELECT candidate.* FROM catalog.visible_platform_account candidate
      JOIN catalog.legacy_entity_alias candidate_alias ON candidate_alias.target_uuid=candidate.id
        AND candidate_alias.entity_type='platform_accounts'
      WHERE candidate.institution_id=page.id ORDER BY candidate_alias.legacy_id LIMIT 51
    ) account ON true
    JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=account.id
      AND alias.entity_type='platform_accounts'
    LEFT JOIN catalog.legacy_entity_alias channel ON channel.target_uuid=account.id
      AND channel.entity_type='channels'
    LEFT JOIN catalog.account_external_identity native ON native.platform_account_id=account.id
      AND native.identity_namespace=account.platform::text||':native_id' AND native.valid_to IS NULL
    LEFT JOIN analytics.account_latest metric ON metric.platform_account_id=account.id
      AND metric.metric_key='subscribers'
    LEFT JOIN LATERAL ops_and_admin.legacy_account_presentation(account.id) presentation ON true
), accounts AS (
    SELECT institution_id,jsonb_agg(item ORDER BY legacy_id) FILTER(WHERE ordinal<=50) AS items,
      CASE WHEN count(*)>50 THEN max(legacy_id) FILTER(WHERE ordinal=50) END AS next_after
    FROM account_rows GROUP BY institution_id
)
SELECT jsonb_build_object('id',page.id,'legacyId',page.legacy_id,
  'name',page.canonical_name,'shortName',page.short_name,'rowVersion',page.row_version,
  'accounts',coalesce(accounts.items,'[]'::jsonb),'nextAccountAfter',accounts.next_after,
  'officialRatings',ratings.items) AS item
FROM page LEFT JOIN accounts ON accounts.institution_id=page.id
CROSS JOIN LATERAL (
  SELECT jsonb_object_agg(category.key,jsonb_build_object('rank',observation.rank,
    'score',observation.score)) AS items
  FROM (VALUES('all','social'),('telegram','telegram'),('vk','vk'),('max','max'),
    ('rutube','rutube')) category(key,source)
  LEFT JOIN LATERAL (
    SELECT rank,score FROM rating.official_institution_rating_observation
    WHERE institution_id=page.id AND category=category.source
    ORDER BY fetched_at DESC,id DESC LIMIT 1
  ) observation ON true
) ratings ORDER BY page.legacy_id
"""

CATALOG_ACCOUNTS = """
SELECT jsonb_build_object('id',account.id,'legacyId',alias.legacy_id,
  'channelId',channel.legacy_id,'institutionId',account.institution_id,
  'platform',account.platform,'externalKey',account.canonical_external_id,
  'username',account.current_username,'title',account.current_title,'url',account.current_url,
  'accessMode',account.access_mode,'enabled',account.enabled,'rowVersion',account.row_version,
  'nativeId',native.external_id,'subscribers',metric.value,
  'legacyAccessMode',presentation.access_mode,'lastErrorCode',presentation.last_error_code) AS item
FROM catalog.visible_platform_account account
JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=account.id
  AND alias.entity_type='platform_accounts'
LEFT JOIN catalog.legacy_entity_alias channel ON channel.target_uuid=account.id
  AND channel.entity_type='channels'
LEFT JOIN catalog.account_external_identity native ON native.platform_account_id=account.id
  AND native.identity_namespace=account.platform::text||':native_id' AND native.valid_to IS NULL
LEFT JOIN analytics.account_latest metric ON metric.platform_account_id=account.id
  AND metric.metric_key='subscribers'
LEFT JOIN LATERAL ops_and_admin.legacy_account_presentation(account.id) presentation ON true
WHERE account.institution_id=%(institution)s AND alias.legacy_id>%(after)s
ORDER BY alias.legacy_id LIMIT %(limit)s
"""

CATALOG_STATUS = """
SELECT (SELECT count(*) FROM catalog.visible_platform_account account
        JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=account.id
          AND alias.entity_type='channels') AS channels,
  (SELECT count(*) FROM catalog.visible_platform_account) AS accounts,
  (SELECT count(*) FROM catalog.visible_institution) AS institutions,
  (SELECT count(*) FROM catalog.visible_platform_account WHERE platform='max') AS max_accounts,
  (SELECT count(*) FROM catalog.visible_platform_account account
    JOIN catalog.account_external_identity native ON native.platform_account_id=account.id
      AND native.identity_namespace='max:native_id' AND native.valid_to IS NULL
    WHERE account.platform='max' AND native.external_id<>'') AS max_native_ids,
  pg_database_size(current_database()) AS database_bytes,
  coalesce((SELECT value FROM ops_and_admin.operational_checkpoint
    WHERE checkpoint_key='admin.m_rating' AND scope_type='system'),
    jsonb_build_object(
      'period',(SELECT value#>>'{}' FROM ops_and_admin.operational_checkpoint
        WHERE checkpoint_key='m_rating_last_period' AND scope_type='system'),
      'updatedAt',(SELECT value#>>'{}' FROM ops_and_admin.operational_checkpoint
        WHERE checkpoint_key='m_rating_last_updated' AND scope_type='system'),
      'error',CASE WHEN EXISTS(SELECT 1 FROM ops_and_admin.operational_checkpoint
        WHERE checkpoint_key='m_rating_last_error' AND scope_type='system'
          AND value->>'present'='true') THEN 'legacy_source_error' ELSE NULL END)) AS rating
"""

CATALOG_ENVELOPE = """
SELECT jsonb_build_object('action',%(action)s::text,'target',%(target)s::uuid,
  'expected',%(expected)s::bigint,'body',%(body)s::jsonb)::text AS original
"""

CATALOG_COMMAND = """
SELECT ops_and_admin.catalog_command(%(action)s,%(target)s,%(expected)s,%(body)s::jsonb,
  %(actor)s,%(correlation)s) AS result
"""

RESOLVE_ALIAS = """
SELECT target_uuid FROM catalog.legacy_entity_alias
WHERE entity_type=%(type)s AND legacy_id=%(legacy_id)s
"""

ROW_VERSION = """
SELECT row_version FROM {table} WHERE id=%(id)s
"""

PARENT_LEGACY_ID = """
SELECT alias.legacy_id FROM catalog.visible_platform_account account
JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=account.institution_id
  AND alias.entity_type='institutions' WHERE account.id=%(id)s
"""

JOBS = """
SELECT run.id,run.platform::text AS platform,run.scheduled_at,run.started_at,
  run.completed_at,run.status::text AS status,run.account_count,run.error_count,
  run.correlation_id FROM ingest.collection_run run
WHERE (%(platform)s='' OR run.platform::text=%(platform)s)
  AND (%(status)s='' OR run.status::text=%(status)s)
ORDER BY run.started_at DESC,run.id DESC LIMIT %(limit)s
"""

JOB = """
SELECT run.id,run.platform::text AS platform,run.scheduled_at,run.started_at,
  run.completed_at,run.status::text AS status,run.account_count,run.error_count,
  run.correlation_id FROM ingest.collection_run run WHERE run.id=%(job)s
"""

ACCOUNT_RESULTS = """
SELECT result.id,result.platform_account_id,result.started_at,result.completed_at,
  result.status::text AS status,result.discovered_count,result.snapshot_count,
  result.sanitized_error_code FROM ingest.collection_account_result result
WHERE result.collection_run_id=%(job)s ORDER BY result.started_at,result.id
LIMIT %(limit)s
"""

PLATFORM_ACCOUNT = """
SELECT account.id,account.platform::text AS platform,account.enabled,account.row_version,
  account.updated_at FROM catalog.platform_account account
WHERE account.id=%(account)s AND account.deleted_at IS NULL
"""

LOCK_ACCOUNT = PLATFORM_ACCOUNT + " FOR UPDATE"

UPDATE_ACCOUNT = """
UPDATE catalog.platform_account SET enabled=%(enabled)s,row_version=row_version+1,
  updated_at=transaction_timestamp()
WHERE id=%(account)s AND row_version=%(expected)s
RETURNING id,platform::text AS platform,enabled,row_version,updated_at
"""

INSERT_REVISION = """
INSERT INTO analytics.dataset_revision(cause,correlation_id)
VALUES('configuration',%(correlation)s) RETURNING id
"""

QUEUE_PROJECTION = """
INSERT INTO ops_and_admin.outbox_event(dataset_revision_id,event_type,aggregate_type,
  aggregate_id,affected_tags,payload)
VALUES(%(revision)s,'projection.rebuild.requested','projection','core',
  ARRAY['publications','overview','comparison'],
  jsonb_build_object('revision',%(revision)s::bigint,'cause','configuration'))
ON CONFLICT(dataset_revision_id,event_type,aggregate_type,aggregate_id) DO NOTHING
"""

QUEUE_ENABLED = """
INSERT INTO ops_and_admin.outbox_event(dataset_revision_id,event_type,aggregate_type,
  aggregate_id,affected_tags,payload)
VALUES(%(revision)s,'platform_account.enabled_changed','platform_account',%(account)s::text,
  ARRAY[%(tag)s::text],jsonb_build_object('enabled',%(enabled)s::boolean,
    'rowVersion',%(row_version)s::bigint))
"""

AUDIT_ENABLED = """
INSERT INTO ops_and_admin.audit_log(subject,action,target_type,target_id,correlation_id,
  before_state,after_state,outcome)
VALUES(%(actor)s,'platform_account.set_enabled','platform_account',%(account)s,%(correlation)s,
  %(before)s::jsonb,%(after)s::jsonb,%(outcome)s)
"""
