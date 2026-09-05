-- Materialize the exact legacy overview card semantics at publication time.
-- V1--V7 are immutable. The public API reads only these revision-pinned rows;
-- raw snapshots are scanned solely by the maintenance-owned rebuild function.

SET ROLE migration_owner;
SET lock_timeout = '10s';
SET statement_timeout = '15min';
SET client_min_messages = warning;

CREATE TABLE analytics.legacy_overview_account (
    dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id),
    platform analytics.platform_scope NOT NULL,
    entity_id uuid NOT NULL,
    position integer NOT NULL CHECK (position > 0),
    account_id uuid NOT NULL REFERENCES catalog.platform_account(id),
    legacy_id bigint CHECK (legacy_id IS NULL OR legacy_id > 0),
    legacy_route text,
    account_platform catalog.platform_code NOT NULL,
    canonical_external_id text NOT NULL,
    username text,
    title text,
    url text,
    access_mode catalog.access_mode NOT NULL,
    enabled boolean NOT NULL,
    subscriber_count bigint CHECK (subscriber_count IS NULL OR subscriber_count >= 0),
    subscriber_display text,
    subscriber_observed_at timestamptz,
    latest_poll_started_at timestamptz,
    latest_poll_completed_at timestamptz,
    latest_poll_status ingest.run_status,
    latest_error_code text,
    last_checked_at timestamptz,
    PRIMARY KEY (platform, entity_id, account_id),
    UNIQUE (platform, entity_id, position),
    CHECK (url IS NULL OR url ~ '^https://')
);

CREATE INDEX legacy_overview_account_revision_entity_idx
    ON analytics.legacy_overview_account (
        dataset_revision_id, platform, entity_id, position
    );

COMMENT ON TABLE analytics.legacy_overview_account IS
    'Revision-pinned account metadata used by legacy overview cards; rows include disabled accounts outside Telegram exactly as the legacy overview did.';

CREATE TABLE analytics.legacy_overview_card (
    dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id),
    platform analytics.platform_scope NOT NULL,
    period_key text NOT NULL CHECK (period_key IN ('3h', '1d', '7d', '30d')),
    entity_type text NOT NULL CHECK (entity_type IN ('channels', 'institutions')),
    entity_id uuid NOT NULL,
    legacy_id bigint NOT NULL CHECK (legacy_id > 0),
    legacy_route text,
    institution_id uuid NOT NULL REFERENCES catalog.institution(id),
    institution_legacy_id bigint NOT NULL CHECK (institution_legacy_id > 0),
    canonical_name text NOT NULL,
    short_name text,
    sort_name text NOT NULL,
    search_text text NOT NULL,
    account_count integer NOT NULL CHECK (account_count >= 0),
    enabled_account_count integer NOT NULL CHECK (enabled_account_count >= 0),
    connected_platform_count integer NOT NULL CHECK (
        connected_platform_count >= 0 AND connected_platform_count <= 4
    ),
    subscriber_count bigint CHECK (subscriber_count IS NULL OR subscriber_count >= 0),
    last_checked_at timestamptz,
    last_error_code text,
    status_code text NOT NULL CHECK (status_code IN (
        'no_account', 'all_accounts_disabled', 'last_poll_failed',
        'polling', 'awaiting_first_poll', 'connected'
    )),
    rating_rank integer CHECK (rating_rank IS NULL OR rating_rank > 0),
    rating_score numeric,
    rating_period text,
    rating_fetched_at timestamptz,
    total_publication_count bigint CHECK (
        total_publication_count IS NULL OR total_publication_count >= 0
    ),
    activity_publication_count bigint CHECK (
        activity_publication_count IS NULL OR activity_publication_count >= 0
    ),
    new_publication_count bigint CHECK (
        new_publication_count IS NULL OR new_publication_count >= 0
    ),
    total_views numeric,
    median_views numeric,
    previous_total_views numeric,
    previous_median_views numeric,
    delta_total_views numeric,
    delta_median_views numeric,
    total_reactions numeric,
    median_reactions numeric,
    previous_total_reactions numeric,
    previous_median_reactions numeric,
    delta_total_reactions numeric,
    delta_median_reactions numeric,
    total_comments numeric,
    median_comments numeric,
    previous_total_comments numeric,
    previous_median_comments numeric,
    delta_total_comments numeric,
    delta_median_comments numeric,
    total_shares numeric,
    median_shares numeric,
    previous_total_shares numeric,
    previous_median_shares numeric,
    delta_total_shares numeric,
    delta_median_shares numeric,
    as_of timestamptz NOT NULL,
    refreshed_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY (platform, period_key, entity_id),
    CHECK ((platform = 'telegram') = (entity_type = 'channels')),
    CHECK (
        platform <> 'all'
        OR (
            total_publication_count IS NULL
            AND activity_publication_count IS NULL
            AND new_publication_count IS NULL
            AND total_views IS NULL AND median_views IS NULL
            AND previous_total_views IS NULL AND previous_median_views IS NULL
            AND delta_total_views IS NULL AND delta_median_views IS NULL
            AND total_reactions IS NULL AND median_reactions IS NULL
            AND previous_total_reactions IS NULL AND previous_median_reactions IS NULL
            AND delta_total_reactions IS NULL AND delta_median_reactions IS NULL
            AND total_comments IS NULL AND median_comments IS NULL
            AND previous_total_comments IS NULL AND previous_median_comments IS NULL
            AND delta_total_comments IS NULL AND delta_median_comments IS NULL
            AND total_shares IS NULL AND median_shares IS NULL
            AND previous_total_shares IS NULL AND previous_median_shares IS NULL
            AND delta_total_shares IS NULL AND delta_median_shares IS NULL
        )
    )
);

CREATE INDEX legacy_overview_card_revision_scope_name_idx
    ON analytics.legacy_overview_card (
        dataset_revision_id, platform, period_key, sort_name, entity_id
    );
CREATE INDEX legacy_overview_card_revision_scope_rating_idx
    ON analytics.legacy_overview_card (
        dataset_revision_id, platform, period_key, rating_rank, entity_id
    );
CREATE INDEX legacy_overview_card_revision_scope_activity_idx
    ON analytics.legacy_overview_card (
        dataset_revision_id, platform, period_key,
        median_reactions, total_reactions, total_views, entity_id
    );

COMMENT ON TABLE analytics.legacy_overview_card IS
    'Revision-pinned legacy / overview cards. Windows use (start,end], new-publication zero baselines retain platform gates, and all never mixes counters across platforms.';

REVOKE ALL ON TABLE
    analytics.legacy_overview_card,
    analytics.legacy_overview_account
FROM PUBLIC;

GRANT SELECT ON
    analytics.legacy_overview_card,
    analytics.legacy_overview_account
TO api_read, migration_bridge, maintenance;

-- Preserve every earlier projection rebuild, including V6 comparison rows.
ALTER FUNCTION analytics.rebuild_core_projections(bigint)
    RENAME TO rebuild_core_projections_v6;

REVOKE ALL ON FUNCTION analytics.rebuild_core_projections_v6(bigint)
    FROM PUBLIC, migration_bridge, maintenance, api_write_admin;

CREATE FUNCTION analytics.rebuild_core_projections(p_dataset_revision_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, catalog, ingest, analytics, rating, ops_and_admin, migration
SET lock_timeout = '10s'
SET statement_timeout = '15min'
AS $function$
DECLARE
    base_result jsonb;
    revision_as_of timestamptz;
    overview_account_rows bigint;
    overview_card_rows bigint;
BEGIN
    base_result := analytics.rebuild_core_projections_v6(p_dataset_revision_id);

    SELECT committed_at
      INTO STRICT revision_as_of
      FROM analytics.dataset_revision
     WHERE id = p_dataset_revision_id;

    DELETE FROM analytics.legacy_overview_card;
    DELETE FROM analytics.legacy_overview_account;

    WITH latest_account_metric AS (
        SELECT DISTINCT ON (snapshot.platform_account_id)
               snapshot.platform_account_id,
               snapshot.subscriber_count,
               snapshot.subscriber_display,
               snapshot.observed_at
          FROM ingest.account_metric_snapshot AS snapshot
         WHERE snapshot.observed_at <= revision_as_of
           AND snapshot.collected_at <= revision_as_of
           AND snapshot.quality <> 'invalid'
         ORDER BY snapshot.platform_account_id, snapshot.observed_at DESC, snapshot.id DESC
    ), latest_account_result AS (
        SELECT DISTINCT ON (result.platform_account_id)
               result.platform_account_id,
               result.started_at,
               CASE WHEN result.completed_at <= revision_as_of
                    THEN result.completed_at END AS completed_at,
               CASE WHEN result.completed_at IS NULL
                          OR result.completed_at > revision_as_of
                    THEN 'running'::ingest.run_status
                    ELSE result.status END AS status,
               CASE
                   WHEN result.completed_at <= revision_as_of
                    AND result.status IN ('failed', 'partial') THEN
                       coalesce(result.sanitized_error_code, 'collection_failed')
                   WHEN result.completed_at <= revision_as_of
                       THEN result.sanitized_error_code
                   ELSE NULL
               END AS error_code
          FROM ingest.collection_account_result AS result
         WHERE result.started_at <= revision_as_of
         ORDER BY result.platform_account_id, result.started_at DESC, result.id DESC
    ), legacy_error AS (
        SELECT identity.target_uuid AS platform_account_id,
               bool_or(identity.source_table = 'channels')
                   FILTER (WHERE evidence.id IS NOT NULL) AS channel_error,
               bool_or(identity.source_table = 'platform_accounts')
                   FILTER (WHERE evidence.id IS NOT NULL) AS platform_account_error
          FROM migration.legacy_identity_map AS identity
          LEFT JOIN migration.legacy_evidence AS evidence
            ON evidence.batch_id = identity.last_seen_batch_id
           AND evidence.source_table = identity.source_table
           AND evidence.source_pk = identity.source_pk
           AND evidence.source_row_hash = identity.source_row_hash
           AND evidence.evidence_kind = 'sanitized_last_error'
           AND evidence.evidence->>'present' = 'true'
         WHERE identity.target_type = 'platform_account'
           AND identity.source_table IN ('channels', 'platform_accounts')
         GROUP BY identity.target_uuid
    ), last_checked AS (
        SELECT DISTINCT ON (checkpoint.scope_id)
               checkpoint.scope_id AS platform_account_id,
               checkpoint.source_observed_at
          FROM ops_and_admin.operational_checkpoint AS checkpoint
         WHERE checkpoint.scope_type = 'account'
           AND checkpoint.checkpoint_key = 'last_checked_at'
           AND checkpoint.source_observed_at <= revision_as_of
         ORDER BY checkpoint.scope_id, checkpoint.source_observed_at DESC,
                  checkpoint.updated_at DESC, checkpoint.id DESC
    ), account_fact AS (
        SELECT account.id,
               account.institution_id,
               account.platform,
               account.canonical_external_id,
               account.current_username,
               account.current_title,
               account.current_url,
               account.access_mode,
               account.enabled,
               channel_alias.legacy_id AS channel_legacy_id,
               channel_alias.legacy_route AS channel_legacy_route,
               platform_alias.legacy_id AS platform_legacy_id,
               platform_alias.legacy_route AS platform_legacy_route,
               metric.subscriber_count,
               metric.subscriber_display,
               metric.observed_at AS subscriber_observed_at,
               result.started_at AS latest_poll_started_at,
               result.completed_at AS latest_poll_completed_at,
               result.status AS latest_poll_status,
               CASE
                   WHEN result.platform_account_id IS NOT NULL THEN result.error_code
                   WHEN coalesce(error.channel_error, false)
                     OR coalesce(error.platform_account_error, false)
                       THEN 'legacy_error_present'
                   ELSE NULL
               END AS latest_error_code,
               greatest(
                   checked.source_observed_at,
                   result.completed_at,
                   result.started_at,
                   metric.observed_at
               ) AS last_checked_at,
               coalesce(error.channel_error, false) AS channel_error,
               coalesce(error.platform_account_error, false) AS platform_account_error
          FROM catalog.platform_account AS account
          LEFT JOIN catalog.legacy_entity_alias AS channel_alias
            ON channel_alias.target_uuid = account.id
           AND channel_alias.entity_type = 'channels'
          LEFT JOIN catalog.legacy_entity_alias AS platform_alias
            ON platform_alias.target_uuid = account.id
           AND platform_alias.entity_type = 'platform_accounts'
          LEFT JOIN latest_account_metric AS metric
            ON metric.platform_account_id = account.id
          LEFT JOIN latest_account_result AS result
            ON result.platform_account_id = account.id
          LEFT JOIN legacy_error AS error
            ON error.platform_account_id = account.id
          LEFT JOIN last_checked AS checked
            ON checked.platform_account_id = account.id
    ), telegram_dimensions AS (
        SELECT 'telegram'::analytics.platform_scope AS platform,
               account.id AS entity_id,
               account.institution_id
          FROM account_fact AS account
         WHERE account.platform = 'telegram'
           AND account.enabled
           AND account.channel_legacy_id IS NOT NULL
    ), institution_dimensions AS (
        SELECT scope.platform,
               institution.id AS entity_id,
               institution.id AS institution_id
          FROM catalog.institution AS institution
         CROSS JOIN (VALUES
             ('all'::analytics.platform_scope),
             ('vk'::analytics.platform_scope),
             ('max'::analytics.platform_scope),
             ('rutube'::analytics.platform_scope)
         ) AS scope(platform)
    ), dimensions AS (
        SELECT * FROM telegram_dimensions
        UNION ALL
        SELECT * FROM institution_dimensions
    ), selected_accounts AS (
        SELECT dimension.platform AS scope_platform,
               dimension.entity_id,
               account.*,
               CASE
                   WHEN dimension.platform = 'telegram' THEN account.channel_legacy_id
                   ELSE coalesce(account.platform_legacy_id, account.channel_legacy_id)
               END AS selected_legacy_id,
               CASE
                   WHEN dimension.platform = 'telegram' THEN account.channel_legacy_route
                   ELSE coalesce(account.platform_legacy_route, account.channel_legacy_route)
               END AS selected_legacy_route,
               CASE
                   WHEN account.latest_poll_status IS NOT NULL THEN account.latest_error_code
                   WHEN dimension.platform = 'telegram' AND account.channel_error
                       THEN 'legacy_error_present'
                   WHEN dimension.platform <> 'telegram' AND account.platform_account_error
                       THEN 'legacy_error_present'
                   ELSE NULL
               END AS selected_error_code
          FROM dimensions AS dimension
          JOIN account_fact AS account
            ON account.institution_id = dimension.institution_id
           AND (
               (dimension.platform = 'telegram' AND account.id = dimension.entity_id)
               OR dimension.platform = 'all'
               OR account.platform::text = dimension.platform::text
           )
    )
    INSERT INTO analytics.legacy_overview_account (
        dataset_revision_id, platform, entity_id, position, account_id,
        legacy_id, legacy_route, account_platform, canonical_external_id,
        username, title, url, access_mode, enabled, subscriber_count,
        subscriber_display, subscriber_observed_at, latest_poll_started_at,
        latest_poll_completed_at, latest_poll_status, latest_error_code,
        last_checked_at
    )
    SELECT p_dataset_revision_id,
           account.scope_platform,
           account.entity_id,
           row_number() OVER (
               PARTITION BY account.scope_platform, account.entity_id
               ORDER BY account.platform, lower(coalesce(
                   nullif(account.current_title, ''),
                   nullif(account.current_username, ''),
                   account.canonical_external_id
               )), account.id
           )::integer,
           account.id,
           account.selected_legacy_id,
           account.selected_legacy_route,
           account.platform,
           account.canonical_external_id,
           account.current_username,
           account.current_title,
           account.current_url,
           account.access_mode,
           account.enabled,
           account.subscriber_count,
           account.subscriber_display,
           account.subscriber_observed_at,
           account.latest_poll_started_at,
           account.latest_poll_completed_at,
           account.latest_poll_status,
           account.selected_error_code,
           account.last_checked_at
      FROM selected_accounts AS account;

    GET DIAGNOSTICS overview_account_rows = ROW_COUNT;

    WITH periods(period_key, duration) AS (VALUES
        ('3h'::text, interval '3 hours'),
        ('1d'::text, interval '1 day'),
        ('7d'::text, interval '7 days'),
        ('30d'::text, interval '30 days')
    ), activity_windows AS (
        SELECT period.period_key,
               0 AS window_index,
               revision_as_of - period.duration AS window_start,
               revision_as_of AS window_end
          FROM periods AS period
        UNION ALL
        SELECT period.period_key,
               1,
               revision_as_of - period.duration * 2,
               revision_as_of - period.duration
          FROM periods AS period
    ), telegram_dimensions AS (
        SELECT 'telegram'::analytics.platform_scope AS platform,
               account.id AS entity_id,
               'channels'::text AS entity_type,
               channel_alias.legacy_id,
               channel_alias.legacy_route,
               account.institution_id
          FROM catalog.platform_account AS account
          JOIN catalog.legacy_entity_alias AS channel_alias
            ON channel_alias.target_uuid = account.id
           AND channel_alias.entity_type = 'channels'
         WHERE account.platform = 'telegram'
           AND account.enabled
    ), institution_dimensions AS (
        SELECT scope.platform,
               institution.id AS entity_id,
               'institutions'::text AS entity_type,
               institution_alias.legacy_id,
               institution_alias.legacy_route,
               institution.id AS institution_id
          FROM catalog.institution AS institution
          JOIN catalog.legacy_entity_alias AS institution_alias
            ON institution_alias.target_uuid = institution.id
           AND institution_alias.entity_type = 'institutions'
         CROSS JOIN (VALUES
             ('all'::analytics.platform_scope),
             ('vk'::analytics.platform_scope),
             ('max'::analytics.platform_scope),
             ('rutube'::analytics.platform_scope)
         ) AS scope(platform)
    ), dimensions AS (
        SELECT * FROM telegram_dimensions
        UNION ALL
        SELECT * FROM institution_dimensions
    ), activity_publications AS (
        SELECT 'telegram'::analytics.platform_scope AS platform,
               account.id AS entity_id,
               publication.id AS publication_id,
               publication.published_at,
               publication.history_completeness,
               publication.synthetic_baseline_allowed
          FROM ingest.publication AS publication
          JOIN catalog.platform_account AS account
            ON account.id = publication.primary_account_id
          JOIN catalog.legacy_entity_alias AS channel_alias
            ON channel_alias.target_uuid = account.id
           AND channel_alias.entity_type = 'channels'
         WHERE account.platform = 'telegram'
           AND account.enabled
           AND publication.published_at <= revision_as_of
           AND publication.created_at <= revision_as_of
        UNION ALL
        SELECT account.platform::text::analytics.platform_scope,
               account.institution_id,
               publication.id,
               publication.published_at,
               publication.history_completeness,
               publication.synthetic_baseline_allowed
          FROM ingest.publication AS publication
          JOIN catalog.platform_account AS account
            ON account.id = publication.primary_account_id
         WHERE account.platform <> 'telegram'
           AND publication.published_at <= revision_as_of
           AND publication.created_at <= revision_as_of
    ), window_observations AS (
        SELECT activity_window.period_key,
               activity_window.window_index,
               activity_window.window_start,
               activity_window.window_end,
               publication.platform,
               publication.entity_id,
               publication.publication_id,
               publication.published_at,
               publication.history_completeness,
               publication.synthetic_baseline_allowed,
               snapshot.views_count,
               snapshot.reactions_count,
               snapshot.comments_count,
               snapshot.shares_count,
               row_number() OVER (
                   PARTITION BY activity_window.period_key, activity_window.window_index,
                                publication.publication_id
                   ORDER BY snapshot.observed_at, snapshot.published_month, snapshot.id
               ) AS first_position,
               row_number() OVER (
                   PARTITION BY activity_window.period_key, activity_window.window_index,
                                publication.publication_id
                   ORDER BY snapshot.observed_at DESC,
                            snapshot.published_month DESC, snapshot.id DESC
               ) AS latest_position,
               count(*) OVER (
                   PARTITION BY activity_window.period_key, activity_window.window_index,
                                publication.publication_id
               ) AS observation_count
          FROM activity_windows AS activity_window
          JOIN activity_publications AS publication
            ON publication.published_at <= activity_window.window_end
          JOIN ingest.publication_metric_snapshot AS snapshot
            ON snapshot.publication_id = publication.publication_id
           AND snapshot.observed_at > activity_window.window_start
           AND snapshot.observed_at <= activity_window.window_end
           AND snapshot.collected_at <= revision_as_of
           AND NOT snapshot.synthetic
           AND snapshot.quality <> 'invalid'
    ), publication_bounds AS (
        SELECT observation.period_key,
               observation.window_index,
               observation.window_start,
               observation.window_end,
               observation.platform,
               observation.entity_id,
               observation.publication_id,
               observation.published_at,
               observation.history_completeness,
               observation.synthetic_baseline_allowed,
               max(observation.observation_count) AS observation_count,
               max(observation.views_count)
                   FILTER (WHERE observation.first_position = 1) AS first_views,
               max(observation.views_count)
                   FILTER (WHERE observation.latest_position = 1) AS latest_views,
               max(observation.reactions_count)
                   FILTER (WHERE observation.first_position = 1) AS first_reactions,
               max(observation.reactions_count)
                   FILTER (WHERE observation.latest_position = 1) AS latest_reactions,
               max(observation.comments_count)
                   FILTER (WHERE observation.first_position = 1) AS first_comments,
               max(observation.comments_count)
                   FILTER (WHERE observation.latest_position = 1) AS latest_comments,
               max(observation.shares_count)
                   FILTER (WHERE observation.first_position = 1) AS first_shares,
               max(observation.shares_count)
                   FILTER (WHERE observation.latest_position = 1) AS latest_shares
          FROM window_observations AS observation
         GROUP BY observation.period_key, observation.window_index,
                  observation.window_start, observation.window_end,
                  observation.platform, observation.entity_id,
                  observation.publication_id, observation.published_at,
                  observation.history_completeness,
                  observation.synthetic_baseline_allowed
    ), publication_delta AS (
        SELECT bounds.*,
               CASE
                   WHEN bounds.latest_views IS NULL THEN NULL
                   WHEN bounds.published_at >= bounds.window_start
                    AND ((bounds.platform = 'telegram' AND bounds.synthetic_baseline_allowed)
                      OR (bounds.platform <> 'telegram'
                          AND bounds.history_completeness = 'complete'))
                       THEN bounds.latest_views::numeric
                   WHEN bounds.observation_count >= 2 AND bounds.first_views IS NOT NULL
                       THEN bounds.latest_views::numeric - bounds.first_views::numeric
                   ELSE NULL
               END AS views_delta,
               CASE
                   WHEN bounds.latest_reactions IS NULL THEN NULL
                   WHEN bounds.published_at >= bounds.window_start
                    AND ((bounds.platform = 'telegram' AND bounds.synthetic_baseline_allowed)
                      OR (bounds.platform <> 'telegram'
                          AND bounds.history_completeness = 'complete'))
                       THEN bounds.latest_reactions::numeric
                   WHEN bounds.observation_count >= 2 AND bounds.first_reactions IS NOT NULL
                       THEN bounds.latest_reactions::numeric - bounds.first_reactions::numeric
                   ELSE NULL
               END AS reactions_delta,
               CASE
                   WHEN bounds.latest_comments IS NULL THEN NULL
                   WHEN bounds.published_at >= bounds.window_start
                    AND ((bounds.platform = 'telegram' AND bounds.synthetic_baseline_allowed)
                      OR (bounds.platform <> 'telegram'
                          AND bounds.history_completeness = 'complete'))
                       THEN bounds.latest_comments::numeric
                   WHEN bounds.observation_count >= 2 AND bounds.first_comments IS NOT NULL
                       THEN bounds.latest_comments::numeric - bounds.first_comments::numeric
                   ELSE NULL
               END AS comments_delta,
               CASE
                   WHEN bounds.latest_shares IS NULL THEN NULL
                   WHEN bounds.published_at >= bounds.window_start
                    AND ((bounds.platform = 'telegram' AND bounds.synthetic_baseline_allowed)
                      OR (bounds.platform <> 'telegram'
                          AND bounds.history_completeness = 'complete'))
                       THEN bounds.latest_shares::numeric
                   WHEN bounds.observation_count >= 2 AND bounds.first_shares IS NOT NULL
                       THEN bounds.latest_shares::numeric - bounds.first_shares::numeric
                   ELSE NULL
               END AS shares_delta
          FROM publication_bounds AS bounds
    ), activity_count AS (
        SELECT delta.period_key,
               delta.window_index,
               delta.platform,
               delta.entity_id,
               count(*)::bigint AS publication_count
          FROM publication_delta AS delta
         WHERE delta.views_delta IS NOT NULL
            OR delta.reactions_delta IS NOT NULL
            OR delta.comments_delta IS NOT NULL
            OR delta.shares_delta IS NOT NULL
         GROUP BY delta.period_key, delta.window_index,
                  delta.platform, delta.entity_id
    ), metric_delta AS (
        SELECT delta.period_key,
               delta.window_index,
               delta.platform,
               delta.entity_id,
               delta.publication_id,
               metric.metric_key,
               metric.delta_value
          FROM publication_delta AS delta
         CROSS JOIN LATERAL (VALUES
             ('views'::analytics.metric_key, delta.views_delta),
             ('reactions'::analytics.metric_key, delta.reactions_delta),
             ('comments'::analytics.metric_key, delta.comments_delta),
             ('shares'::analytics.metric_key, delta.shares_delta)
         ) AS metric(metric_key, delta_value)
         WHERE metric.delta_value IS NOT NULL
    ), ranked_metric AS (
        SELECT metric.*,
               row_number() OVER (
                   PARTITION BY metric.period_key, metric.window_index,
                                metric.platform, metric.entity_id, metric.metric_key
                   ORDER BY metric.delta_value, metric.publication_id
               ) AS rank_position,
               count(*) OVER (
                   PARTITION BY metric.period_key, metric.window_index,
                                metric.platform, metric.entity_id, metric.metric_key
               ) AS sample_size
          FROM metric_delta AS metric
    ), metric_aggregate AS (
        SELECT metric.period_key,
               metric.window_index,
               metric.platform,
               metric.entity_id,
               metric.metric_key,
               sum(metric.delta_value) AS total_value,
               floor(avg(metric.delta_value) FILTER (
                   WHERE metric.rank_position IN (
                       (metric.sample_size + 1) / 2,
                       (metric.sample_size + 2) / 2
                   )
               ) + 0.5) AS median_value
          FROM ranked_metric AS metric
         GROUP BY metric.period_key, metric.window_index,
                  metric.platform, metric.entity_id, metric.metric_key
    ), metric_pivot AS (
        SELECT metric.period_key,
               metric.platform,
               metric.entity_id,
               max(metric.total_value) FILTER (
                   WHERE metric.window_index = 0 AND metric.metric_key = 'views'
               ) AS total_views,
               max(metric.median_value) FILTER (
                   WHERE metric.window_index = 0 AND metric.metric_key = 'views'
               ) AS median_views,
               max(metric.total_value) FILTER (
                   WHERE metric.window_index = 1 AND metric.metric_key = 'views'
               ) AS previous_total_views,
               max(metric.median_value) FILTER (
                   WHERE metric.window_index = 1 AND metric.metric_key = 'views'
               ) AS previous_median_views,
               max(metric.total_value) FILTER (
                   WHERE metric.window_index = 0 AND metric.metric_key = 'reactions'
               ) AS total_reactions,
               max(metric.median_value) FILTER (
                   WHERE metric.window_index = 0 AND metric.metric_key = 'reactions'
               ) AS median_reactions,
               max(metric.total_value) FILTER (
                   WHERE metric.window_index = 1 AND metric.metric_key = 'reactions'
               ) AS previous_total_reactions,
               max(metric.median_value) FILTER (
                   WHERE metric.window_index = 1 AND metric.metric_key = 'reactions'
               ) AS previous_median_reactions,
               max(metric.total_value) FILTER (
                   WHERE metric.window_index = 0 AND metric.metric_key = 'comments'
               ) AS total_comments,
               max(metric.median_value) FILTER (
                   WHERE metric.window_index = 0 AND metric.metric_key = 'comments'
               ) AS median_comments,
               max(metric.total_value) FILTER (
                   WHERE metric.window_index = 1 AND metric.metric_key = 'comments'
               ) AS previous_total_comments,
               max(metric.median_value) FILTER (
                   WHERE metric.window_index = 1 AND metric.metric_key = 'comments'
               ) AS previous_median_comments,
               max(metric.total_value) FILTER (
                   WHERE metric.window_index = 0 AND metric.metric_key = 'shares'
               ) AS total_shares,
               max(metric.median_value) FILTER (
                   WHERE metric.window_index = 0 AND metric.metric_key = 'shares'
               ) AS median_shares,
               max(metric.total_value) FILTER (
                   WHERE metric.window_index = 1 AND metric.metric_key = 'shares'
               ) AS previous_total_shares,
               max(metric.median_value) FILTER (
                   WHERE metric.window_index = 1 AND metric.metric_key = 'shares'
               ) AS previous_median_shares
          FROM metric_aggregate AS metric
         GROUP BY metric.period_key, metric.platform, metric.entity_id
    ), publication_count AS (
        SELECT period.period_key,
               publication.platform,
               publication.entity_id,
               count(*)::bigint AS total_count,
               count(*) FILTER (
                   WHERE publication.published_at >= revision_as_of - period.duration
                     AND publication.published_at <= revision_as_of
               )::bigint AS new_count
          FROM periods AS period
          JOIN activity_publications AS publication ON true
         GROUP BY period.period_key, publication.platform, publication.entity_id
    ), account_summary AS (
        SELECT account.platform,
               account.entity_id,
               count(*)::integer AS account_count,
               count(*) FILTER (WHERE account.enabled)::integer AS enabled_account_count,
               count(DISTINCT account.account_platform)
                   FILTER (WHERE account.enabled)::integer AS connected_platform_count,
               sum(account.subscriber_count) AS subscriber_count,
               max(account.last_checked_at) AS last_checked_at,
               min(account.latest_error_code)
                   FILTER (WHERE account.latest_error_code IS NOT NULL) AS last_error_code
          FROM analytics.legacy_overview_account AS account
         WHERE account.dataset_revision_id = p_dataset_revision_id
         GROUP BY account.platform, account.entity_id
    ), latest_rating AS (
        SELECT DISTINCT ON (observation.institution_id, observation.category)
               observation.institution_id,
               observation.category,
               observation.rank,
               observation.score,
               observation.period,
               observation.fetched_at
          FROM rating.official_rating_observation AS observation
         WHERE observation.fetched_at <= revision_as_of
           AND observation.category IN ('social', 'telegram', 'vk', 'max', 'rutube')
         ORDER BY observation.institution_id, observation.category,
                  observation.fetched_at DESC, observation.id DESC
    ), card_source AS (
        SELECT dimension.platform,
               period.period_key,
               dimension.entity_type,
               dimension.entity_id,
               dimension.legacy_id,
               dimension.legacy_route,
               institution.id AS institution_id,
               institution_alias.legacy_id AS institution_legacy_id,
               institution.canonical_name,
               institution.short_name,
               btrim(regexp_replace(replace(lower(coalesce(
                   nullif(institution.short_name, ''),
                   nullif(institution.canonical_name, ''),
                   telegram_account.current_title,
                   telegram_account.current_username,
                   ''
               )), 'ё', 'е'), '[[:space:]]+', ' ', 'g')) AS sort_name,
               btrim(regexp_replace(replace(lower(concat_ws(' ',
                   institution.short_name,
                   institution.canonical_name,
                   telegram_account.current_title
               )), 'ё', 'е'), '[[:space:]]+', ' ', 'g')) AS search_text,
               coalesce(account.account_count, 0) AS account_count,
               coalesce(account.enabled_account_count, 0) AS enabled_account_count,
               coalesce(account.connected_platform_count, 0) AS connected_platform_count,
               account.subscriber_count,
               account.last_checked_at,
               account.last_error_code,
               CASE
                   WHEN coalesce(account.account_count, 0) = 0 THEN 'no_account'
                   WHEN coalesce(account.enabled_account_count, 0) = 0
                       THEN 'all_accounts_disabled'
                   WHEN account.last_error_code IS NOT NULL THEN 'last_poll_failed'
                   WHEN dimension.platform = 'all' THEN 'connected'
                   WHEN account.last_checked_at IS NOT NULL THEN 'polling'
                   ELSE 'awaiting_first_poll'
               END AS status_code,
               rating.rank AS rating_rank,
               rating.score AS rating_score,
               rating.period AS rating_period,
               rating.fetched_at AS rating_fetched_at,
               CASE WHEN dimension.platform = 'all' THEN NULL
                    ELSE coalesce(publication.total_count, 0) END
                   AS total_publication_count,
               CASE WHEN dimension.platform = 'all' THEN NULL
                    ELSE coalesce(activity.publication_count, 0) END
                   AS activity_publication_count,
               CASE WHEN dimension.platform = 'all' THEN NULL
                    ELSE coalesce(publication.new_count, 0) END
                   AS new_publication_count,
               metric.total_views,
               metric.median_views,
               metric.previous_total_views,
               metric.previous_median_views,
               metric.total_reactions,
               metric.median_reactions,
               metric.previous_total_reactions,
               metric.previous_median_reactions,
               metric.total_comments,
               metric.median_comments,
               metric.previous_total_comments,
               metric.previous_median_comments,
               metric.total_shares,
               metric.median_shares,
               metric.previous_total_shares,
               metric.previous_median_shares,
               revision_as_of AS as_of
          FROM dimensions AS dimension
         CROSS JOIN periods AS period
          JOIN catalog.institution AS institution
            ON institution.id = dimension.institution_id
          JOIN catalog.legacy_entity_alias AS institution_alias
            ON institution_alias.target_uuid = institution.id
           AND institution_alias.entity_type = 'institutions'
          LEFT JOIN analytics.legacy_overview_account AS telegram_account_row
            ON dimension.platform = 'telegram'
           AND telegram_account_row.dataset_revision_id = p_dataset_revision_id
           AND telegram_account_row.platform = dimension.platform
           AND telegram_account_row.entity_id = dimension.entity_id
           AND telegram_account_row.position = 1
          LEFT JOIN catalog.platform_account AS telegram_account
            ON telegram_account.id = telegram_account_row.account_id
          LEFT JOIN account_summary AS account
            ON account.platform = dimension.platform
           AND account.entity_id = dimension.entity_id
          LEFT JOIN publication_count AS publication
            ON publication.period_key = period.period_key
           AND publication.platform = dimension.platform
           AND publication.entity_id = dimension.entity_id
          LEFT JOIN activity_count AS activity
            ON activity.period_key = period.period_key
           AND activity.window_index = 0
           AND activity.platform = dimension.platform
           AND activity.entity_id = dimension.entity_id
          LEFT JOIN metric_pivot AS metric
            ON metric.period_key = period.period_key
           AND metric.platform = dimension.platform
           AND metric.entity_id = dimension.entity_id
          LEFT JOIN latest_rating AS rating
            ON rating.institution_id = dimension.institution_id
           AND rating.category = CASE dimension.platform::text
               WHEN 'all' THEN 'social'
               ELSE dimension.platform::text
           END
    )
    INSERT INTO analytics.legacy_overview_card (
        dataset_revision_id, platform, period_key, entity_type, entity_id,
        legacy_id, legacy_route, institution_id, institution_legacy_id,
        canonical_name, short_name, sort_name, search_text,
        account_count, enabled_account_count, connected_platform_count,
        subscriber_count, last_checked_at, last_error_code, status_code,
        rating_rank, rating_score, rating_period, rating_fetched_at,
        total_publication_count, activity_publication_count, new_publication_count,
        total_views, median_views, previous_total_views, previous_median_views,
        delta_total_views, delta_median_views,
        total_reactions, median_reactions,
        previous_total_reactions, previous_median_reactions,
        delta_total_reactions, delta_median_reactions,
        total_comments, median_comments, previous_total_comments,
        previous_median_comments, delta_total_comments, delta_median_comments,
        total_shares, median_shares, previous_total_shares,
        previous_median_shares, delta_total_shares, delta_median_shares,
        as_of, refreshed_at
    )
    SELECT p_dataset_revision_id,
           card.platform,
           card.period_key,
           card.entity_type,
           card.entity_id,
           card.legacy_id,
           card.legacy_route,
           card.institution_id,
           card.institution_legacy_id,
           card.canonical_name,
           card.short_name,
           card.sort_name,
           card.search_text,
           card.account_count,
           card.enabled_account_count,
           card.connected_platform_count,
           card.subscriber_count,
           card.last_checked_at,
           card.last_error_code,
           card.status_code,
           card.rating_rank,
           card.rating_score,
           card.rating_period,
           card.rating_fetched_at,
           card.total_publication_count,
           card.activity_publication_count,
           card.new_publication_count,
           card.total_views,
           card.median_views,
           card.previous_total_views,
           card.previous_median_views,
           CASE WHEN card.total_views IS NOT NULL
                  AND card.previous_total_views IS NOT NULL
                THEN card.total_views - card.previous_total_views END,
           CASE WHEN card.median_views IS NOT NULL
                  AND card.previous_median_views IS NOT NULL
                THEN card.median_views - card.previous_median_views END,
           card.total_reactions,
           card.median_reactions,
           card.previous_total_reactions,
           card.previous_median_reactions,
           CASE WHEN card.total_reactions IS NOT NULL
                  AND card.previous_total_reactions IS NOT NULL
                THEN card.total_reactions - card.previous_total_reactions END,
           CASE WHEN card.median_reactions IS NOT NULL
                  AND card.previous_median_reactions IS NOT NULL
                THEN card.median_reactions - card.previous_median_reactions END,
           card.total_comments,
           card.median_comments,
           card.previous_total_comments,
           card.previous_median_comments,
           CASE WHEN card.total_comments IS NOT NULL
                  AND card.previous_total_comments IS NOT NULL
                THEN card.total_comments - card.previous_total_comments END,
           CASE WHEN card.median_comments IS NOT NULL
                  AND card.previous_median_comments IS NOT NULL
                THEN card.median_comments - card.previous_median_comments END,
           card.total_shares,
           card.median_shares,
           card.previous_total_shares,
           card.previous_median_shares,
           CASE WHEN card.total_shares IS NOT NULL
                  AND card.previous_total_shares IS NOT NULL
                THEN card.total_shares - card.previous_total_shares END,
           CASE WHEN card.median_shares IS NOT NULL
                  AND card.previous_median_shares IS NOT NULL
                THEN card.median_shares - card.previous_median_shares END,
           card.as_of,
           transaction_timestamp()
      FROM card_source AS card;

    GET DIAGNOSTICS overview_card_rows = ROW_COUNT;

    RETURN base_result || jsonb_build_object(
        'legacy_overview_accounts', overview_account_rows,
        'legacy_overview_cards', overview_card_rows,
        'legacy_overview_semantics_version', 1
    );
END
$function$;

COMMENT ON FUNCTION analytics.rebuild_core_projections(bigint) IS
    'Publishes all core projections plus the atomic legacy overview read model; V8 preserves V6 comparison and V5 period semantics.';

REVOKE ALL ON FUNCTION analytics.rebuild_core_projections(bigint) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION analytics.rebuild_core_projections(bigint)
    TO migration_bridge, maintenance, api_write_admin;

RESET ROLE;
