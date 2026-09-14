"""Детальные публичные чтения поверх каталога и инкрементальной витрины.

Списки и карточки читают ``analytics.publication_latest``: у каждой метрики
там хранится собственное последнее известное значение. Только история идёт в
партиционированный ряд; её запрос всегда фиксирует ``published_month`` и сам
выбирает последнюю коррекцию каждого sampling bucket.
"""
from __future__ import annotations


INSTITUTION = """
WITH selected AS (
    SELECT institution.id AS institution_id, alias.legacy_id,
           institution.canonical_name, institution.short_name
      FROM catalog.legacy_entity_alias alias
      JOIN catalog.visible_institution institution ON institution.id=alias.target_uuid
     WHERE alias.entity_type='institutions' AND alias.legacy_id=%(legacy_id)s
), publication_fact AS (
    SELECT publication.id,
           CASE WHEN latest.views_quality IN ('invalid','suspected_reset')
                THEN NULL ELSE latest.views_count END AS views_count,
           CASE WHEN latest.reactions_quality IN ('invalid','suspected_reset')
                THEN NULL ELSE latest.reactions_count END AS reactions_count,
           latest.views_quality, latest.reactions_quality
      FROM selected
      JOIN catalog.visible_platform_account account ON account.institution_id=selected.institution_id
       AND (%(platform)s='all' OR account.platform::text=%(platform)s)
      JOIN ingest.visible_publication publication ON publication.primary_account_id=account.id
       AND publication.published_at>%(as_of)s::timestamptz-
           CASE %(period)s WHEN '3h' THEN interval '3 hours'
                           WHEN '1d' THEN interval '1 day'
                           WHEN '7d' THEN interval '7 days'
                           ELSE interval '30 days' END
       AND publication.published_at<=%(as_of)s::timestamptz
       AND publication.created_at<=%(as_of)s::timestamptz
      LEFT JOIN analytics.publication_latest latest ON latest.publication_id=publication.id
       AND latest.observed_at<=%(as_of)s::timestamptz AND NOT latest.synthetic
       AND latest.quality<>'invalid'
), metric AS (
    SELECT value.metric_key, count(value.metric_value)::integer AS sample_size,
           sum(value.metric_value)::numeric AS total_value,
           round(percentile_cont(0.5) WITHIN GROUP (ORDER BY value.metric_value)
                 FILTER (WHERE value.metric_value IS NOT NULL)::numeric,0) AS median_value,
           max(analytics.observation_quality_rank(value.metric_quality))
             FILTER (WHERE value.metric_value IS NOT NULL) AS quality_rank
      FROM publication_fact
     CROSS JOIN LATERAL (VALUES
        ('views', views_count, views_quality),
        ('reactions', reactions_count, reactions_quality)
     ) value(metric_key,metric_value,metric_quality)
     GROUP BY value.metric_key
), metadata AS (
    SELECT jsonb_object_agg(name, jsonb_build_object(
               'value', value, 'asOf', %(as_of)s::timestamptz,
               'datasetRevision', %(revision)s::bigint, 'sampleSize', sample_size,
               'coverage', CASE WHEN (SELECT count(*) FROM publication_fact)=0 THEN NULL
                                ELSE sample_size::numeric/(SELECT count(*) FROM publication_fact) END,
               'quality', analytics.observation_quality_from_rank(quality_rank)::text)) AS body
      FROM (
          SELECT 'total'||initcap(metric_key) AS name, total_value AS value,
                 sample_size, quality_rank FROM metric
          UNION ALL
          SELECT 'median'||initcap(metric_key), median_value,
                 sample_size, quality_rank FROM metric
      ) values_for_metadata
)
SELECT selected.*,
       max(metric.total_value) FILTER (WHERE metric_key='reactions') AS total_reactions,
       max(metric.total_value) FILTER (WHERE metric_key='views') AS total_views,
       max(metric.median_value) FILTER (WHERE metric_key='reactions') AS median_reactions,
       max(metric.median_value) FILTER (WHERE metric_key='views') AS median_views,
       coalesce(max(metric.sample_size),0)::integer AS sample_size,
       CASE WHEN (SELECT count(*) FROM publication_fact)=0 THEN 0::numeric
            ELSE coalesce(max(metric.sample_size),0)::numeric/(SELECT count(*) FROM publication_fact) END AS coverage,
       analytics.observation_quality_from_rank(max(metric.quality_rank))::text AS quality,
       coalesce(metadata.body,'{}'::jsonb) AS aggregate_metadata,
       %(as_of)s::timestamptz AS as_of
  FROM selected CROSS JOIN metadata LEFT JOIN metric ON true
 GROUP BY selected.institution_id,selected.legacy_id,selected.canonical_name,
          selected.short_name,metadata.body
"""


ACCOUNT = """
WITH target AS (
    SELECT account.id
      FROM catalog.visible_platform_account account
     WHERE %(entity_uuid)s::uuid IS NOT NULL AND account.id=%(entity_uuid)s::uuid
    UNION ALL
    SELECT account.id
      FROM catalog.legacy_entity_alias requested
      JOIN catalog.visible_platform_account account ON account.id=requested.target_uuid
     WHERE %(entity_uuid)s::uuid IS NULL AND requested.entity_type=%(legacy_type)s
       AND requested.legacy_id=%(legacy_id)s
), aliases AS (
    SELECT alias.target_uuid,
           min(alias.legacy_id) FILTER (WHERE alias.entity_type='channels') AS channel_legacy_id,
           min(alias.legacy_id) FILTER (WHERE alias.entity_type='platform_accounts') AS platform_account_legacy_id
      FROM catalog.legacy_entity_alias alias
     WHERE alias.entity_type IN ('channels','platform_accounts')
     GROUP BY alias.target_uuid
)
SELECT account.id AS account_id, canonical.legacy_id, canonical.entity_type,
       aliases.channel_legacy_id, aliases.platform_account_legacy_id,
       institution.id AS institution_id, institution_alias.legacy_id AS institution_legacy_id,
       institution.canonical_name, institution.short_name, account.platform::text AS platform,
       account.canonical_external_id, account.current_username, account.current_title,
       account.current_url, account.access_mode::text AS access_mode, account.enabled,
       (SELECT count(*) FROM ingest.visible_publication publication
         WHERE publication.primary_account_id=account.id) AS publication_count,
       (SELECT snapshot.observed_at FROM ingest.account_metric_snapshot_active snapshot
         WHERE snapshot.platform_account_id=account.id
           AND snapshot.observed_at<=%(as_of)s::timestamptz
           AND snapshot.collected_at<=%(as_of)s::timestamptz
         ORDER BY snapshot.observed_at DESC,snapshot.id DESC LIMIT 1) AS latest_observed_at,
       %(as_of)s::timestamptz AS as_of
  FROM target
  JOIN catalog.visible_platform_account account ON account.id=target.id
  JOIN catalog.visible_institution institution ON institution.id=account.institution_id
  JOIN catalog.legacy_entity_alias institution_alias ON institution_alias.target_uuid=institution.id
   AND institution_alias.entity_type='institutions'
  JOIN LATERAL (
      SELECT alias.legacy_id, alias.entity_type
        FROM catalog.legacy_entity_alias alias
       WHERE alias.target_uuid=account.id
         AND alias.entity_type=CASE WHEN account.platform='telegram' THEN 'channels' ELSE 'platform_accounts' END
       ORDER BY alias.legacy_id LIMIT 1) canonical ON true
  LEFT JOIN aliases ON aliases.target_uuid=account.id
"""


ACCOUNT_STATS = """
WITH publications AS (
    SELECT publication.id, publication.history_completeness, publication.published_at
      FROM ingest.visible_publication publication
     WHERE publication.primary_account_id=%(account_id)s::uuid
       AND publication.published_at>=%(as_of)s::timestamptz-make_interval(days=>%(days)s)
       AND publication.published_at<=%(as_of)s::timestamptz
), latest AS (
    SELECT publication.history_completeness,
           CASE WHEN value.metric_quality IN ('invalid','suspected_reset') THEN NULL
                ELSE value.metric_value END AS metric_value,
           value.metric_key, value.metric_quality
      FROM publications publication
      LEFT JOIN analytics.publication_latest snapshot ON snapshot.publication_id=publication.id
       AND snapshot.observed_at<=%(as_of)s::timestamptz AND NOT snapshot.synthetic
       AND snapshot.quality<>'invalid'
     CROSS JOIN LATERAL (VALUES
        ('views',snapshot.views_count,snapshot.views_quality),
        ('reactions',snapshot.reactions_count,snapshot.reactions_quality),
        ('comments',snapshot.comments_count,snapshot.comments_quality)
     ) value(metric_key,metric_value,metric_quality)
), metric AS (
    SELECT metric_key,
           round(percentile_cont(0.5) WITHIN GROUP(ORDER BY metric_value)
                 FILTER(WHERE metric_value IS NOT NULL)::numeric,0) AS median_value,
           count(metric_value)::integer AS sample_size,
           max(analytics.observation_quality_rank(metric_quality))
             FILTER(WHERE metric_value IS NOT NULL) AS quality_rank
      FROM latest GROUP BY metric_key
), subscriber AS (
    SELECT snapshot.subscriber_count
      FROM ingest.account_metric_snapshot_active snapshot
     WHERE snapshot.platform_account_id=%(account_id)s::uuid
       AND snapshot.observed_at<=%(as_of)s::timestamptz
       AND snapshot.collected_at<=%(as_of)s::timestamptz AND snapshot.quality<>'invalid'
     ORDER BY snapshot.observed_at DESC,snapshot.id DESC LIMIT 1
), collection AS (
    SELECT result.sanitized_error_code,result.started_at,result.completed_at,result.status
      FROM ingest.collection_account_result result
     WHERE result.platform_account_id=%(account_id)s::uuid
       AND result.started_at<=%(as_of)s::timestamptz
     ORDER BY result.started_at DESC,result.id DESC LIMIT 1
), yesterday_edge AS (
    -- Значение каждой публикации на границе вчерашних суток по Москве.
    -- Отсюда берутся плашки «за сутки» у плиток: медиана вчера против
    -- медианы сейчас. Одним проходом по диапазону, как в недельном ряду.
    SELECT DISTINCT ON (publication.id) publication.id,
           snapshot.views_count, snapshot.reactions_count, snapshot.comments_count,
           snapshot.views_quality, snapshot.reactions_quality, snapshot.comments_quality
      FROM publications publication
      JOIN ingest.publication_metric_snapshot_active snapshot
        ON snapshot.publication_id=publication.id
       AND snapshot.published_month=date_trunc('month', publication.published_at)::date
     WHERE snapshot.observed_at
           < (((%(as_of)s::timestamptz AT TIME ZONE 'Europe/Moscow')::date)::timestamp
              AT TIME ZONE 'Europe/Moscow')
       AND snapshot.observed_at
           >= (((%(as_of)s::timestamptz AT TIME ZONE 'Europe/Moscow')::date - 3)::timestamp
              AT TIME ZONE 'Europe/Moscow')
       AND snapshot.quality<>'invalid'
     ORDER BY publication.id, snapshot.observed_at DESC, snapshot.id DESC
), yesterday_metric AS (
    SELECT value.metric_key,
           round(percentile_cont(0.5) WITHIN GROUP(ORDER BY value.metric_value)
                 FILTER(WHERE value.metric_value IS NOT NULL)::numeric,0) AS median_value
      FROM yesterday_edge edge
     CROSS JOIN LATERAL (VALUES
        ('views',CASE WHEN edge.views_quality IN ('invalid','suspected_reset')
                      THEN NULL ELSE edge.views_count END),
        ('reactions',CASE WHEN edge.reactions_quality IN ('invalid','suspected_reset')
                          THEN NULL ELSE edge.reactions_count END),
        ('comments',CASE WHEN edge.comments_quality IN ('invalid','suspected_reset')
                         THEN NULL ELSE edge.comments_count END)
     ) value(metric_key,metric_value)
     GROUP BY value.metric_key
), official_rating AS (
    SELECT observation.rank,observation.period
      FROM rating.official_institution_rating_observation observation
     WHERE observation.institution_id=%(institution_id)s::uuid
       AND observation.fetched_at<=%(as_of)s::timestamptz
       AND observation.category=%(platform)s
     -- Порядок по самому периоду, а не по времени загрузки: всю
     -- опубликованную историю мы забираем одним прогоном, и «загружен
     -- позже» перестало означать «свежее». Название месяца переводится в
     -- номер, год берётся из той же строки.
     ORDER BY nullif(regexp_replace(observation.period,'[^0-9]','','g'),'')::int DESC NULLS LAST,
              array_position(ARRAY['Январь','Февраль','Март','Апрель','Май','Июнь',
                                        'Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'],
                                  split_part(observation.period,' ',1)) DESC NULLS LAST,
              observation.fetched_at DESC, observation.id DESC LIMIT 1
), previous_rating AS (
    -- Место в прошлом опубликованном периоде. Рейтинг выходит раз в месяц,
    -- поэтому «предыдущий» здесь — предыдущий месяц, а не предыдущие сутки.
    SELECT observation.rank, observation.period
      FROM rating.official_institution_rating_observation observation
     WHERE observation.institution_id=%(institution_id)s::uuid
       AND observation.fetched_at<=%(as_of)s::timestamptz
       AND observation.category=%(platform)s
       AND observation.period<>(SELECT period FROM official_rating)
     -- Порядок по самому периоду, а не по времени загрузки: всю
     -- опубликованную историю мы забираем одним прогоном, и «загружен
     -- позже» перестало означать «свежее». Название месяца переводится в
     -- номер, год берётся из той же строки.
     ORDER BY nullif(regexp_replace(observation.period,'[^0-9]','','g'),'')::int DESC NULLS LAST,
              array_position(ARRAY['Январь','Февраль','Март','Апрель','Май','Июнь',
                                        'Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'],
                                  split_part(observation.period,' ',1)) DESC NULLS LAST,
              observation.fetched_at DESC, observation.id DESC LIMIT 1
)
SELECT %(days)s::integer AS retention_days,
       (SELECT count(*) FROM publications)::bigint AS post_count,
       (SELECT count(*) FROM publications WHERE history_completeness='complete')::bigint AS monitored,
       coalesce((SELECT jsonb_object_agg(metric_key,jsonb_build_object(
           'value',median_value,'sampleSize',sample_size,
           'coverage',CASE WHEN (SELECT count(*) FROM publications)=0 THEN NULL
                           ELSE sample_size::numeric/(SELECT count(*) FROM publications) END,
           'quality',analytics.observation_quality_from_rank(quality_rank)::text)) FROM metric),'{}'::jsonb) AS medians,
       official_rating.rank AS rating_rank, official_rating.period AS rating_period,
       previous_rating.rank AS previous_rating_rank,
       previous_rating.period AS previous_rating_period,
       -- Вчерашние значения тех же плиток: по ним рисуется плашка «за сутки».
       (SELECT count(*) FROM publications publication
         WHERE publication.published_at
               < (((%(as_of)s::timestamptz AT TIME ZONE 'Europe/Moscow')::date)::timestamp
                  AT TIME ZONE 'Europe/Moscow'))::bigint AS previous_post_count,
       (SELECT count(*) FROM publications publication
         WHERE publication.history_completeness='complete'
           AND publication.published_at
               < (((%(as_of)s::timestamptz AT TIME ZONE 'Europe/Moscow')::date)::timestamp
                  AT TIME ZONE 'Europe/Moscow'))::bigint AS previous_monitored,
       coalesce((SELECT jsonb_object_agg(metric_key,median_value)
                   FROM yesterday_metric),'{}'::jsonb) AS previous_medians,
       subscriber.subscriber_count,
       CASE WHEN collection.status IN ('failed','partial')
            THEN coalesce(collection.sanitized_error_code,'collection_failed') END AS last_error,
       greatest(collection.completed_at,collection.started_at) AS last_checked_at
  FROM (SELECT 1) singleton
  LEFT JOIN subscriber ON true LEFT JOIN collection ON true LEFT JOIN official_rating ON true
  LEFT JOIN previous_rating ON true
"""


INSTITUTION_ACCOUNT_COUNT = """
SELECT count(*)::bigint AS total
  FROM catalog.legacy_entity_alias institution_alias
  JOIN catalog.visible_institution institution ON institution.id=institution_alias.target_uuid
  JOIN catalog.visible_platform_account account ON account.institution_id=institution.id
 WHERE institution_alias.entity_type='institutions' AND institution_alias.legacy_id=%(legacy_id)s
   AND (%(platform)s='all' OR account.platform::text=%(platform)s)
"""


INSTITUTION_ACCOUNTS = """
WITH page AS (
    SELECT account.*, institution.canonical_name, institution.short_name,
           institution_alias.legacy_id AS institution_legacy_id
      FROM catalog.legacy_entity_alias institution_alias
      JOIN catalog.visible_institution institution ON institution.id=institution_alias.target_uuid
      JOIN catalog.visible_platform_account account ON account.institution_id=institution.id
     WHERE institution_alias.entity_type='institutions' AND institution_alias.legacy_id=%(legacy_id)s
       AND (%(platform)s='all' OR account.platform::text=%(platform)s)
       AND (%(after_id)s::uuid IS NULL OR account.id>%(after_id)s::uuid)
     ORDER BY account.id LIMIT %(fetch_limit)s
), totals AS (
    SELECT publication.primary_account_id AS platform_account_id,count(*)::bigint AS publication_count,
           max(publication.published_at) AS observed_at
      FROM page
      LEFT JOIN ingest.visible_publication publication ON publication.primary_account_id=page.id
     GROUP BY publication.primary_account_id
)
SELECT page.*, canonical.legacy_id, canonical.entity_type,
       channel.legacy_id AS channel_legacy_id, generic.legacy_id AS platform_account_legacy_id,
       coalesce(totals.publication_count,0)::bigint AS publication_count, totals.observed_at,
       %(as_of)s::timestamptz AS as_of
  FROM page
  JOIN LATERAL (
      SELECT alias.legacy_id,alias.entity_type FROM catalog.legacy_entity_alias alias
       WHERE alias.target_uuid=page.id
         AND alias.entity_type=CASE WHEN page.platform='telegram' THEN 'channels' ELSE 'platform_accounts' END
       ORDER BY alias.legacy_id LIMIT 1) canonical ON true
  LEFT JOIN LATERAL (SELECT min(legacy_id) AS legacy_id FROM catalog.legacy_entity_alias
       WHERE target_uuid=page.id AND entity_type='channels') channel ON true
  LEFT JOIN LATERAL (SELECT min(legacy_id) AS legacy_id FROM catalog.legacy_entity_alias
       WHERE target_uuid=page.id AND entity_type='platform_accounts') generic ON true
  LEFT JOIN totals ON totals.platform_account_id=page.id
 ORDER BY page.id
"""


ACCOUNT_PUBLICATIONS = """
WITH page AS (
    SELECT publication.*
      FROM ingest.visible_publication publication
     WHERE publication.primary_account_id=%(account_id)s::uuid
       AND publication.published_at>=%(as_of)s::timestamptz-make_interval(days=>%(days)s)
       AND publication.published_at<=%(as_of)s::timestamptz
       AND EXISTS (SELECT 1 FROM catalog.legacy_entity_alias alias
                    WHERE alias.target_uuid=publication.id AND alias.entity_type=%(publication_legacy_type)s)
       AND (%(after_id)s::uuid IS NULL OR (publication.published_at,publication.id)<
           (SELECT cursor.published_at,cursor.id FROM ingest.visible_publication cursor
             WHERE cursor.id=%(after_id)s::uuid AND cursor.primary_account_id=%(account_id)s::uuid))
     ORDER BY publication.published_at DESC,publication.id DESC LIMIT %(fetch_limit)s
)
SELECT page.id AS publication_id, alias.legacy_id, alias.entity_type, alias.legacy_route,
       identity.external_id, identity.public_url, page.published_at,page.publication_type,
       page.deleted_at,page.history_completeness::text,page.is_repost,page.quality_flags,
       account.platform::text AS platform,
       (SELECT count(*) FROM ingest.publication_identity author
         WHERE author.publication_id=page.id AND author.role='joint_author') AS joint_authors,
       latest.views_count,latest.views_observed_at,latest.views_quality::text AS views_quality,
       latest.reactions_count,latest.reactions_observed_at,latest.reactions_quality::text AS reactions_quality,
       latest.comments_count,latest.comments_observed_at,latest.comments_quality::text AS comments_quality,
       latest.shares_count,latest.shares_observed_at,latest.shares_quality::text AS shares_quality
  FROM page
  JOIN catalog.visible_platform_account account ON account.id=page.primary_account_id
  JOIN LATERAL (SELECT candidate.* FROM catalog.legacy_entity_alias candidate
       WHERE candidate.target_uuid=page.id AND candidate.entity_type=%(publication_legacy_type)s
       ORDER BY candidate.legacy_id LIMIT 1) alias ON true
  LEFT JOIN LATERAL (SELECT candidate.external_id,candidate.public_url
       FROM ingest.publication_identity candidate
       WHERE candidate.publication_id=page.id AND candidate.role='primary'
       ORDER BY candidate.id LIMIT 1) identity ON true
  LEFT JOIN analytics.publication_latest latest ON latest.publication_id=page.id
   AND latest.observed_at<=%(as_of)s::timestamptz AND NOT latest.synthetic AND latest.quality<>'invalid'
 ORDER BY page.published_at DESC,page.id DESC
"""


PUBLICATION = """
WITH target AS (
    SELECT publication.id
      FROM ingest.visible_publication publication
     WHERE %(entity_uuid)s::uuid IS NOT NULL AND publication.id=%(entity_uuid)s::uuid
    UNION ALL
    SELECT publication.id
      FROM catalog.legacy_entity_alias requested
      JOIN ingest.visible_publication publication ON publication.id=requested.target_uuid
     WHERE %(entity_uuid)s::uuid IS NULL AND requested.entity_type=%(legacy_type)s
       AND requested.legacy_id=%(legacy_id)s
)
SELECT publication.id AS publication_id, alias.legacy_id,alias.entity_type,
       account.institution_id,account_alias.legacy_id AS account_legacy_id,
       account_alias.entity_type AS account_legacy_type,account.current_title AS account_name,
       account.current_username AS account_username,identity.external_id,identity.public_url,
       publication.published_at,publication.publication_type,publication.is_repost,
       publication.quality_flags AS presentation_flags,
       (SELECT count(*) FROM ingest.publication_identity author
         WHERE author.publication_id=publication.id AND author.role='joint_author') AS joint_authors,
       publication.deleted_at,account.platform::text AS platform,
       latest.views_count,latest.views_observed_at,latest.views_quality::text AS views_quality,
       latest.reactions_count,latest.reactions_observed_at,latest.reactions_quality::text AS reactions_quality,
       latest.comments_count,latest.comments_observed_at,latest.comments_quality::text AS comments_quality,
       latest.shares_count,latest.shares_observed_at,latest.shares_quality::text AS shares_quality,
       coalesce(quality.quality,'unknown') AS quality,
       coalesce(latest.interval_uncertain,false) AS interval_uncertain,
       coalesce(latest.synthetic,false) AS synthetic,
       publication.history_completeness::text AS history_completeness,
       coalesce(latest.observed_at,%(as_of)s::timestamptz) AS observed_at
  FROM target
  JOIN ingest.visible_publication publication ON publication.id=target.id
  JOIN catalog.visible_platform_account account ON account.id=publication.primary_account_id
  JOIN LATERAL (SELECT candidate.legacy_id,candidate.entity_type
       FROM catalog.legacy_entity_alias candidate
       WHERE candidate.target_uuid=publication.id
         AND candidate.entity_type=CASE WHEN account.platform='telegram' THEN 'posts' ELSE 'platform_posts' END
       ORDER BY candidate.legacy_id LIMIT 1) alias ON true
  LEFT JOIN LATERAL (SELECT candidate.legacy_id,candidate.entity_type
       FROM catalog.legacy_entity_alias candidate
       WHERE candidate.target_uuid=account.id
         AND candidate.entity_type=CASE WHEN account.platform='telegram' THEN 'channels' ELSE 'platform_accounts' END
       ORDER BY candidate.legacy_id LIMIT 1) account_alias ON true
  LEFT JOIN LATERAL (SELECT candidate.external_id,candidate.public_url
       FROM ingest.publication_identity candidate
       WHERE candidate.publication_id=publication.id AND candidate.role='primary'
       ORDER BY candidate.id LIMIT 1) identity ON true
  LEFT JOIN analytics.publication_latest latest ON latest.publication_id=publication.id
   AND latest.observed_at<=%(as_of)s::timestamptz AND NOT latest.synthetic AND latest.quality<>'invalid'
  LEFT JOIN LATERAL (
      SELECT analytics.observation_quality_from_rank(max(analytics.observation_quality_rank(value.metric_quality)))::text AS quality
        FROM (VALUES
          (CASE WHEN latest.views_quality IN ('invalid','suspected_reset') THEN NULL ELSE latest.views_count END,latest.views_quality),
          (CASE WHEN latest.reactions_quality IN ('invalid','suspected_reset') THEN NULL ELSE latest.reactions_count END,latest.reactions_quality),
          (CASE WHEN latest.comments_quality IN ('invalid','suspected_reset') THEN NULL ELSE latest.comments_count END,latest.comments_quality),
          (CASE WHEN latest.shares_quality IN ('invalid','suspected_reset') THEN NULL ELSE latest.shares_count END,latest.shares_quality)
        ) value(metric_value,metric_quality) WHERE value.metric_value IS NOT NULL) quality ON true
"""


HISTORY = """
WITH ranked AS MATERIALIZED (
    SELECT snapshot.*,
           row_number() OVER (PARTITION BY snapshot.publication_id,snapshot.sampling_bucket
                              ORDER BY snapshot.correction_sequence DESC) AS correction_position
      FROM ingest.publication_metric_snapshot snapshot
     WHERE snapshot.published_month=%(published_month)s::date
       AND snapshot.publication_id=%(publication_id)s::uuid
       AND snapshot.observed_at<=%(as_of)s::timestamptz
       AND snapshot.collected_at<=%(as_of)s::timestamptz
), snapshots AS MATERIALIZED (
    SELECT * FROM ranked WHERE correction_position=1
), page AS (
    SELECT snapshot.* FROM snapshots snapshot
     WHERE %(after_snapshot_id)s::bigint IS NULL OR
           (snapshot.observed_at,snapshot.published_month,snapshot.id)<(
             SELECT cursor.observed_at,cursor.published_month,cursor.id FROM snapshots cursor
              WHERE cursor.id=%(after_snapshot_id)s::bigint)
     ORDER BY snapshot.observed_at DESC,snapshot.published_month DESC,snapshot.id DESC
     LIMIT %(fetch_limit)s+1
), decorated AS (
    SELECT page.*,
           coalesce((SELECT jsonb_object_agg(reaction.reaction_key,reaction.reaction_count)
             FROM ingest.reaction_breakdown reaction
            WHERE reaction.snapshot_published_month=page.published_month
              AND reaction.snapshot_id=page.id),'{}'::jsonb) AS reaction_breakdown
      FROM page
), windowed AS (
    SELECT decorated.*,
           lag(decorated.views_count) OVER chronology AS previous_views,
           lag(decorated.reactions_count) OVER chronology AS previous_reactions,
           lag(decorated.comments_count) OVER chronology AS previous_comments,
           lag(decorated.shares_count) OVER chronology AS previous_shares,
           lag(decorated.reaction_breakdown) OVER chronology AS previous_breakdown,
           row_number() OVER (ORDER BY decorated.observed_at DESC,decorated.published_month DESC,decorated.id DESC) AS position
      FROM decorated
    WINDOW chronology AS (ORDER BY decorated.observed_at,decorated.published_month,decorated.id)
)
SELECT windowed.id AS snapshot_id,windowed.*,
       windowed.views_count-windowed.previous_views AS delta_views,
       windowed.reactions_count-windowed.previous_reactions AS delta_reactions,
       windowed.comments_count-windowed.previous_comments AS delta_comments,
       windowed.shares_count-windowed.previous_shares AS delta_shares,
       jsonb_strip_nulls(jsonb_build_object(
         'sourceFingerprint',windowed.source_fingerprint,
         'supersedesSnapshotId',windowed.supersedes_snapshot_id::text,
         'correctionSequence',windowed.correction_sequence,
         'correctionReason',windowed.correction_reason,
         'reactionDetailsSource','canonical')) AS lineage,
       delta_reactions.breakdown AS delta_reaction_breakdown,
       coalesce(analytics.ordered_history_reactions(windowed.reaction_breakdown::text,false),'[]'::jsonb) AS reaction_entries,
       delta_reactions.entries AS delta_reaction_entries
  FROM windowed
 CROSS JOIN LATERAL (
    SELECT computed.entries,
           CASE WHEN computed.entries IS NULL THEN NULL
                ELSE (SELECT coalesce(jsonb_object_agg(item->>'reaction',item->'count'),'{}'::jsonb)
                        FROM jsonb_array_elements(computed.entries) item) END AS breakdown
      FROM (SELECT CASE WHEN windowed.reactions_count IS NULL OR windowed.previous_reactions IS NULL THEN NULL
                        ELSE (SELECT coalesce(jsonb_agg(jsonb_build_object(
                               'reaction',changed.key,'count',changed.difference)
                               ORDER BY changed.key COLLATE "C"),'[]'::jsonb)
                                FROM (SELECT keys.key,
                                      coalesce((windowed.reaction_breakdown->>keys.key)::bigint,0)
                                      -coalesce((windowed.previous_breakdown->>keys.key)::bigint,0) AS difference
                                        FROM (SELECT jsonb_object_keys(windowed.reaction_breakdown) AS key
                                              UNION SELECT jsonb_object_keys(coalesce(windowed.previous_breakdown,'{}'::jsonb))) keys
                                     ) changed WHERE changed.difference<>0) END AS entries) computed
 ) delta_reactions
 WHERE windowed.position<=%(fetch_limit)s
 ORDER BY windowed.observed_at DESC,windowed.published_month DESC,windowed.id DESC
"""


NEIGHBOURS = """
SELECT
  (SELECT alias.legacy_id FROM ingest.visible_publication neighbour
    JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=neighbour.id AND alias.entity_type=%(legacy_type)s
   WHERE neighbour.primary_account_id=publication.primary_account_id
     AND (neighbour.published_at,neighbour.id)<(publication.published_at,publication.id)
   ORDER BY neighbour.published_at DESC,neighbour.id DESC LIMIT 1) AS previous,
  (SELECT alias.legacy_id FROM ingest.visible_publication neighbour
    JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=neighbour.id AND alias.entity_type=%(legacy_type)s
   WHERE neighbour.primary_account_id=publication.primary_account_id
     AND (neighbour.published_at,neighbour.id)>(publication.published_at,publication.id)
   ORDER BY neighbour.published_at,neighbour.id LIMIT 1) AS next
  FROM ingest.visible_publication publication WHERE publication.id=%(publication_id)s::uuid
"""

ACCOUNT_DAILY = """
-- Недельная динамика аккаунта: сколько постов вышло в каждый из последних
-- семи дней, какими они оказались по медиане, и сколько за эти сутки набрали
-- все отслеживаемые посты вместе.
--
-- Медианы считаются по постам этого дня, а суммы — по всем постам площадки:
-- это разные вопросы. Медиана отвечает «каким вышел типичный пост», сумма —
-- «сколько площадка набрала за сутки», и второе совпадает с числом на
-- карточке обзора.
--
-- Дни нарезаются по московскому времени — так же, как подписаны все даты на
-- экране. Границей суток служит последний замер до полуночи, поэтому прирост
-- за день — это разница двух границ, а не сумма отдельных наблюдений.
WITH bounds AS (
    SELECT (%(as_of)s::timestamptz AT TIME ZONE 'Europe/Moscow')::date AS today
), days AS (
    SELECT generate_series(bounds.today - 6, bounds.today, interval '1 day')::date AS metric_day
      FROM bounds
), published AS (
    SELECT (publication.published_at AT TIME ZONE 'Europe/Moscow')::date AS metric_day,
           publication.id
      FROM ingest.visible_publication publication
     CROSS JOIN bounds
     WHERE publication.primary_account_id=%(account_id)s::uuid
       AND publication.published_at<=%(as_of)s::timestamptz
       AND (publication.published_at AT TIME ZONE 'Europe/Moscow')::date >= bounds.today - 6
), valued AS (
    SELECT published.metric_day,
           CASE WHEN latest.reactions_quality IN ('invalid','suspected_reset')
                THEN NULL ELSE latest.reactions_count END AS reactions,
           CASE WHEN latest.views_quality IN ('invalid','suspected_reset')
                THEN NULL ELSE latest.views_count END AS views
      FROM published
      LEFT JOIN analytics.publication_latest latest ON latest.publication_id=published.id
       AND latest.observed_at<=%(as_of)s::timestamptz
       AND NOT latest.synthetic AND latest.quality<>'invalid'
), tracked AS (
    -- Все посты площадки, а не только вышедшие на этой неделе: за сутки
    -- набирают и старые. Месяц публикации передаётся явно — это ключ
    -- партиционирования снимков.
    SELECT publication.id,
           date_trunc('month', publication.published_at)::date AS published_month
      FROM ingest.visible_publication publication
     WHERE publication.primary_account_id=%(account_id)s::uuid
       AND publication.published_at<=%(as_of)s::timestamptz
), edges AS (
    -- Граница суток — последний замер публикации в эти сутки. Берётся одним
    -- проходом по диапазону вместо восьми точечных поисков на публикацию:
    -- на полутора сотнях постов это 800 мс против полусотни.
    SELECT DISTINCT ON (tracked.id, (snapshot.observed_at AT TIME ZONE 'Europe/Moscow')::date)
           tracked.id,
           (snapshot.observed_at AT TIME ZONE 'Europe/Moscow')::date AS metric_day,
           snapshot.reactions_count, snapshot.views_count
      FROM tracked
     CROSS JOIN bounds
      JOIN ingest.publication_metric_snapshot_active snapshot
        ON snapshot.publication_id=tracked.id
       AND snapshot.published_month=tracked.published_month
     WHERE snapshot.observed_at >= ((bounds.today - 7)::timestamp AT TIME ZONE 'Europe/Moscow')
       AND snapshot.observed_at<=%(as_of)s::timestamptz
       AND snapshot.quality<>'invalid'
     ORDER BY tracked.id,
              (snapshot.observed_at AT TIME ZONE 'Europe/Moscow')::date,
              snapshot.observed_at DESC, snapshot.id DESC
), growth AS (
    -- Прирост за сутки — разница между границей этого дня и границей
    -- предыдущего. Первый день ряда остаётся без пары и в сумму не идёт:
    -- восьмая граница берётся ровно ради него.
    SELECT metric_day,
           greatest(reactions_count - lag(reactions_count) OVER pub, 0) AS reactions_gain,
           greatest(views_count - lag(views_count) OVER pub, 0) AS views_gain
      FROM edges
    WINDOW pub AS (PARTITION BY id ORDER BY metric_day)
), daily_growth AS (
    SELECT metric_day, sum(reactions_gain)::numeric AS total_reactions,
           sum(views_gain)::numeric AS total_views
      FROM growth GROUP BY metric_day
)
SELECT days.metric_day,
       count(valued.metric_day)::integer AS published_count,
       round(percentile_cont(0.5) WITHIN GROUP(ORDER BY valued.reactions)
             FILTER(WHERE valued.reactions IS NOT NULL)::numeric,0) AS median_reactions,
       round(percentile_cont(0.5) WITHIN GROUP(ORDER BY valued.views)
             FILTER(WHERE valued.views IS NOT NULL)::numeric,0) AS median_views,
       max(daily_growth.total_reactions) AS total_reactions,
       max(daily_growth.total_views) AS total_views
  FROM days
  LEFT JOIN valued ON valued.metric_day=days.metric_day
  LEFT JOIN daily_growth ON daily_growth.metric_day=days.metric_day
 GROUP BY days.metric_day
 ORDER BY days.metric_day
"""
