-- Preserve the latest valid metric and same-snapshot engagement observation
-- at each comparison hour. The generic V2 hourly row intentionally represents
-- the latest whole snapshot, so it cannot recover an earlier valid metric when
-- a later snapshot in the same hour contains NULL. V1--V5 are immutable.

SET ROLE migration_owner;
SET lock_timeout = '10s';
SET statement_timeout = '15min';
SET client_min_messages = warning;

CREATE TABLE analytics.comparison_publication_hourly (
    publication_id uuid NOT NULL REFERENCES ingest.publication(id) ON DELETE CASCADE,
    hour_offset integer NOT NULL CHECK (hour_offset >= 0 AND hour_offset <= 336),
    institution_id uuid NOT NULL REFERENCES catalog.institution(id),
    platform_account_id uuid NOT NULL REFERENCES catalog.platform_account(id),
    platform catalog.platform_code NOT NULL,
    views_count bigint CHECK (views_count IS NULL OR views_count >= 0),
    views_quality ingest.observation_quality,
    reactions_count bigint CHECK (reactions_count IS NULL OR reactions_count >= 0),
    reactions_quality ingest.observation_quality,
    comments_count bigint CHECK (comments_count IS NULL OR comments_count >= 0),
    comments_quality ingest.observation_quality,
    shares_count bigint CHECK (shares_count IS NULL OR shares_count >= 0),
    shares_quality ingest.observation_quality,
    engagement_percent numeric CHECK (
        engagement_percent IS NULL OR engagement_percent >= 0
    ),
    engagement_quality ingest.observation_quality,
    dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id),
    PRIMARY KEY (publication_id, hour_offset),
    CHECK ((views_count IS NULL) = (views_quality IS NULL)),
    CHECK ((reactions_count IS NULL) = (reactions_quality IS NULL)),
    CHECK ((comments_count IS NULL) = (comments_quality IS NULL)),
    CHECK ((shares_count IS NULL) = (shares_quality IS NULL)),
    CHECK ((engagement_percent IS NULL) = (engagement_quality IS NULL))
);

CREATE INDEX comparison_publication_hourly_query_idx
    ON analytics.comparison_publication_hourly (
        dataset_revision_id, platform, institution_id,
        platform_account_id, hour_offset, publication_id
    );

COMMENT ON TABLE analytics.comparison_publication_hourly IS
    'Revision-pinned comparison input: latest valid non-NULL metric and same-snapshot engagement ratio known by each whole publication hour.';
COMMENT ON COLUMN analytics.comparison_publication_hourly.engagement_percent IS
    'Latest ratio known by this hour: Telegram reactions/views; VK and RUTUBE sum available reactions, comments, shares per snapshot before dividing by views.';

REVOKE ALL ON TABLE analytics.comparison_publication_hourly FROM PUBLIC;
GRANT SELECT ON analytics.comparison_publication_hourly TO api_read;

-- Keep the V5 implementation private. It still publishes the corrected period
-- projection and all V2 projections while retaining the publisher lock.
ALTER FUNCTION analytics.rebuild_core_projections(bigint)
    RENAME TO rebuild_core_projections_v5;

REVOKE ALL ON FUNCTION analytics.rebuild_core_projections_v5(bigint)
    FROM PUBLIC, migration_bridge, maintenance, api_write_admin;

CREATE FUNCTION analytics.rebuild_core_projections(p_dataset_revision_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, catalog, ingest, analytics
SET lock_timeout = '10s'
SET statement_timeout = '15min'
AS $function$
DECLARE
    base_result jsonb;
    revision_as_of timestamptz;
    comparison_hourly_rows bigint;
BEGIN
    base_result := analytics.rebuild_core_projections_v5(p_dataset_revision_id);

    SELECT committed_at
      INTO STRICT revision_as_of
      FROM analytics.dataset_revision
     WHERE id = p_dataset_revision_id;

    DELETE FROM analytics.comparison_publication_hourly;

    WITH publication_limits AS (
        SELECT publication.id AS publication_id,
               publication.primary_account_id AS platform_account_id,
               account.institution_id,
               account.platform,
               publication.published_at,
               publication.synthetic_baseline_allowed,
               max(cohort.horizon_seconds / 3600)::integer AS max_hour
          FROM analytics.comparison_cohort_member AS member
          JOIN analytics.comparison_cohort AS cohort
            ON cohort.id = member.cohort_id
           AND cohort.dataset_revision_id = p_dataset_revision_id
          JOIN ingest.publication AS publication ON publication.id = member.publication_id
          JOIN catalog.platform_account AS account
            ON account.id = publication.primary_account_id
         GROUP BY publication.id, publication.primary_account_id,
                  account.institution_id, account.platform,
                  publication.published_at,
                  publication.synthetic_baseline_allowed
    ), target_hours AS (
        SELECT limits.*,
               series.hour_offset
          FROM publication_limits AS limits
         CROSS JOIN LATERAL generate_series(0, limits.max_hour) AS series(hour_offset)
    )
    INSERT INTO analytics.comparison_publication_hourly (
        publication_id, hour_offset, institution_id, platform_account_id, platform,
        views_count, views_quality, reactions_count, reactions_quality,
        comments_count, comments_quality, shares_count, shares_quality,
        engagement_percent, engagement_quality, dataset_revision_id
    )
    SELECT target.publication_id,
           target.hour_offset,
           target.institution_id,
           target.platform_account_id,
           target.platform,
           views.value,
           views.quality,
           reactions.value,
           reactions.quality,
           comments.value,
           comments.quality,
           shares.value,
           shares.quality,
           engagement.value,
           engagement.quality,
           p_dataset_revision_id
      FROM target_hours AS target
      LEFT JOIN LATERAL (
          SELECT snapshot.views_count AS value,
                 snapshot.quality
            FROM ingest.publication_metric_snapshot AS snapshot
           WHERE snapshot.publication_id = target.publication_id
             AND snapshot.age_seconds <= target.hour_offset * 3600
             AND snapshot.observed_at <=
                 target.published_at + target.hour_offset * interval '1 hour'
             AND snapshot.observed_at <= revision_as_of
             AND snapshot.collected_at <= revision_as_of
             AND (NOT snapshot.synthetic OR target.synthetic_baseline_allowed)
             AND snapshot.quality <> 'invalid'
             AND snapshot.views_count IS NOT NULL
           ORDER BY snapshot.age_seconds DESC, snapshot.observed_at DESC,
                    snapshot.published_month DESC, snapshot.id DESC
           LIMIT 1
      ) AS views ON true
      LEFT JOIN LATERAL (
          SELECT snapshot.reactions_count AS value,
                 snapshot.quality
            FROM ingest.publication_metric_snapshot AS snapshot
           WHERE snapshot.publication_id = target.publication_id
             AND snapshot.age_seconds <= target.hour_offset * 3600
             AND snapshot.observed_at <=
                 target.published_at + target.hour_offset * interval '1 hour'
             AND snapshot.observed_at <= revision_as_of
             AND snapshot.collected_at <= revision_as_of
             AND (NOT snapshot.synthetic OR target.synthetic_baseline_allowed)
             AND snapshot.quality <> 'invalid'
             AND snapshot.reactions_count IS NOT NULL
           ORDER BY snapshot.age_seconds DESC, snapshot.observed_at DESC,
                    snapshot.published_month DESC, snapshot.id DESC
           LIMIT 1
      ) AS reactions ON true
      LEFT JOIN LATERAL (
          SELECT snapshot.comments_count AS value,
                 snapshot.quality
            FROM ingest.publication_metric_snapshot AS snapshot
           WHERE snapshot.publication_id = target.publication_id
             AND snapshot.age_seconds <= target.hour_offset * 3600
             AND snapshot.observed_at <=
                 target.published_at + target.hour_offset * interval '1 hour'
             AND snapshot.observed_at <= revision_as_of
             AND snapshot.collected_at <= revision_as_of
             AND (NOT snapshot.synthetic OR target.synthetic_baseline_allowed)
             AND snapshot.quality <> 'invalid'
             AND snapshot.comments_count IS NOT NULL
           ORDER BY snapshot.age_seconds DESC, snapshot.observed_at DESC,
                    snapshot.published_month DESC, snapshot.id DESC
           LIMIT 1
      ) AS comments ON true
      LEFT JOIN LATERAL (
          SELECT snapshot.shares_count AS value,
                 snapshot.quality
            FROM ingest.publication_metric_snapshot AS snapshot
           WHERE snapshot.publication_id = target.publication_id
             AND snapshot.age_seconds <= target.hour_offset * 3600
             AND snapshot.observed_at <=
                 target.published_at + target.hour_offset * interval '1 hour'
             AND snapshot.observed_at <= revision_as_of
             AND snapshot.collected_at <= revision_as_of
             AND (NOT snapshot.synthetic OR target.synthetic_baseline_allowed)
             AND snapshot.quality <> 'invalid'
             AND snapshot.shares_count IS NOT NULL
           ORDER BY snapshot.age_seconds DESC, snapshot.observed_at DESC,
                    snapshot.published_month DESC, snapshot.id DESC
           LIMIT 1
      ) AS shares ON true
      LEFT JOIN LATERAL (
          SELECT ratio.value,
                 snapshot.quality
            FROM ingest.publication_metric_snapshot AS snapshot
           CROSS JOIN LATERAL (
               SELECT CASE
                   WHEN snapshot.views_count IS NULL OR snapshot.views_count <= 0 THEN NULL
                   WHEN target.platform = 'telegram' THEN
                       CASE WHEN snapshot.reactions_count IS NULL THEN NULL
                            ELSE snapshot.reactions_count::numeric * 100::numeric
                                 / snapshot.views_count::numeric END
                   WHEN target.platform IN ('vk', 'rutube') THEN
                       CASE
                           WHEN snapshot.reactions_count IS NULL
                            AND snapshot.comments_count IS NULL
                            AND snapshot.shares_count IS NULL THEN NULL
                           ELSE (
                               coalesce(snapshot.reactions_count, 0)::numeric
                               + coalesce(snapshot.comments_count, 0)::numeric
                               + coalesce(snapshot.shares_count, 0)::numeric
                           ) * 100::numeric / snapshot.views_count::numeric
                       END
                   ELSE NULL
               END AS value
           ) AS ratio
           WHERE snapshot.publication_id = target.publication_id
             AND snapshot.age_seconds <= target.hour_offset * 3600
             AND snapshot.observed_at <=
                 target.published_at + target.hour_offset * interval '1 hour'
             AND snapshot.observed_at <= revision_as_of
             AND snapshot.collected_at <= revision_as_of
             AND (NOT snapshot.synthetic OR target.synthetic_baseline_allowed)
             AND snapshot.quality <> 'invalid'
             AND ratio.value IS NOT NULL
           ORDER BY snapshot.age_seconds DESC, snapshot.observed_at DESC,
                    snapshot.published_month DESC, snapshot.id DESC
           LIMIT 1
      ) AS engagement ON true;

    GET DIAGNOSTICS comparison_hourly_rows = ROW_COUNT;

    RETURN base_result || jsonb_build_object(
        'comparison_publication_hourly', comparison_hourly_rows,
        'comparison_semantics_version', 2
    );
END
$function$;

COMMENT ON FUNCTION analytics.rebuild_core_projections(bigint) IS
    'Publishes core projections; comparison semantics v2 preserves latest valid per-metric and same-snapshot engagement observations by hour.';

REVOKE ALL ON FUNCTION analytics.rebuild_core_projections(bigint) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION analytics.rebuild_core_projections(bigint)
    TO migration_bridge, maintenance, api_write_admin;

RESET ROLE;
