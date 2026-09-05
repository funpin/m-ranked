package org.mranked.query.infrastructure;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Types;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.mranked.analytics.domain.CounterMetric;
import org.mranked.analytics.domain.MetricSet;
import org.mranked.analytics.domain.PeriodKey;
import org.mranked.analytics.domain.Platform;
import org.mranked.catalog.domain.InstitutionIdentity;
import org.mranked.catalog.domain.LegacyEntityType;
import org.mranked.ingestion.domain.PublicationIdentity;
import org.mranked.query.application.PublicQueryRepository;
import org.mranked.query.domain.AccountView;
import org.mranked.query.domain.ActivityRatingEntity;
import org.mranked.query.domain.ActivityRatingPublication;
import org.mranked.query.domain.ActivityRatingQuery;
import org.mranked.query.domain.ActivityRatingResult;
import org.mranked.query.domain.ComparisonPoint;
import org.mranked.query.domain.ComparisonSelection;
import org.mranked.query.domain.ComparisonSelectionType;
import org.mranked.query.domain.ComparisonSeries;
import org.mranked.query.domain.ComparisonView;
import org.mranked.query.domain.InstitutionView;
import org.mranked.query.domain.OverviewAccount;
import org.mranked.query.domain.OverviewCard;
import org.mranked.query.domain.OverviewMetric;
import org.mranked.query.domain.OverviewQuery;
import org.mranked.query.domain.PublicationView;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcProjectionQueryRepository implements PublicQueryRepository {
    static final String OVERVIEW_SQL = """
            WITH filtered AS (
                SELECT card.*,
                       row_number() OVER (ORDER BY
                           CASE WHEN :sort = 'name' AND :direction = 'asc'
                                THEN card.sort_name END ASC NULLS LAST,
                           CASE WHEN :sort = 'name' AND :direction = 'desc'
                                THEN card.sort_name END DESC NULLS LAST,
                           CASE WHEN :sort <> 'name' AND :direction = 'asc' THEN
                               CASE :sort
                                   WHEN 'm_rating' THEN card.rating_rank::numeric
                                   WHEN 'coverage' THEN card.connected_platform_count::numeric
                                   WHEN 'accounts' THEN card.account_count::numeric
                                   WHEN 'subscribers' THEN card.subscriber_count::numeric
                                   WHEN 'posts' THEN card.new_publication_count::numeric
                                   WHEN 'views' THEN card.total_views
                                   WHEN 'reactions' THEN card.total_reactions
                                   ELSE card.median_reactions
                               END
                           END ASC NULLS LAST,
                           CASE WHEN :sort <> 'name' AND :direction = 'desc' THEN
                               CASE :sort
                                   WHEN 'm_rating' THEN card.rating_rank::numeric
                                   WHEN 'coverage' THEN card.connected_platform_count::numeric
                                   WHEN 'accounts' THEN card.account_count::numeric
                                   WHEN 'subscribers' THEN card.subscriber_count::numeric
                                   WHEN 'posts' THEN card.new_publication_count::numeric
                                   WHEN 'views' THEN card.total_views
                                   WHEN 'reactions' THEN card.total_reactions
                                   ELSE card.median_reactions
                               END
                           END DESC NULLS LAST,
                           card.sort_name ASC,
                           card.entity_id ASC
                       ) AS page_position
                  FROM analytics.legacy_overview_card AS card
                 WHERE card.dataset_revision_id = :revision
                   AND card.platform::text = :platform
                   AND card.period_key = :period
                   AND (
                       :search = ''
                       OR card.search_text LIKE '%' || btrim(regexp_replace(
                           replace(lower(:search), 'ё', 'е'),
                           '[[:space:]]+', ' ', 'g'
                       )) || '%'
                   )
            ), page AS (
                SELECT filtered.*
                  FROM filtered
                 WHERE CAST(:afterId AS uuid) IS NULL
                    OR filtered.page_position > (
                        SELECT cursor_row.page_position
                          FROM filtered AS cursor_row
                         WHERE cursor_row.entity_id = CAST(:afterId AS uuid)
                    )
                 ORDER BY filtered.page_position
                 LIMIT :fetchLimit
            )
            SELECT page.dataset_revision_id,
                   page.platform::text AS platform,
                   page.period_key,
                   page.entity_type,
                   page.entity_id,
                   page.legacy_id,
                   page.legacy_route,
                   page.institution_id,
                   page.institution_legacy_id,
                   page.canonical_name,
                   page.short_name,
                   page.account_count,
                   page.enabled_account_count,
                   page.connected_platform_count,
                   page.subscriber_count,
                   page.last_checked_at,
                   page.last_error_code,
                   page.status_code,
                   page.rating_rank,
                   page.rating_score,
                   page.rating_period,
                   page.rating_fetched_at,
                   page.total_publication_count,
                   page.activity_publication_count,
                   page.new_publication_count,
                   page.total_views,
                   page.median_views,
                   page.previous_total_views,
                   page.previous_median_views,
                   page.delta_total_views,
                   page.delta_median_views,
                   page.total_reactions,
                   page.median_reactions,
                   page.previous_total_reactions,
                   page.previous_median_reactions,
                   page.delta_total_reactions,
                   page.delta_median_reactions,
                   page.total_comments,
                   page.median_comments,
                   page.previous_total_comments,
                   page.previous_median_comments,
                   page.delta_total_comments,
                   page.delta_median_comments,
                   page.total_shares,
                   page.median_shares,
                   page.previous_total_shares,
                   page.previous_median_shares,
                   page.delta_total_shares,
                   page.delta_median_shares,
                   page.as_of,
                   account.account_id,
                   account.legacy_id AS account_legacy_id,
                   account.legacy_route AS account_legacy_route,
                   account.account_platform::text AS account_platform,
                   account.canonical_external_id AS account_external_id,
                   account.username AS account_username,
                   account.title AS account_title,
                   account.url AS account_url,
                   account.access_mode::text AS account_access_mode,
                   account.enabled AS account_enabled,
                   account.subscriber_count AS account_subscriber_count,
                   account.subscriber_display AS account_subscriber_display,
                   account.subscriber_observed_at AS account_subscriber_observed_at,
                   account.latest_poll_started_at AS account_latest_poll_started_at,
                   account.latest_poll_completed_at AS account_latest_poll_completed_at,
                   account.latest_poll_status::text AS account_latest_poll_status,
                   account.latest_error_code AS account_latest_error_code
              FROM page
              LEFT JOIN analytics.legacy_overview_account AS account
                ON account.dataset_revision_id = page.dataset_revision_id
               AND account.platform = page.platform
               AND account.entity_id = page.entity_id
             ORDER BY page.page_position, account.position
            """;

    static final String INSTITUTION_SQL = """
            WITH metrics AS (
                SELECT m.institution_id,
                       max(m.value) FILTER (
                           WHERE m.metric_key = 'reactions' AND m.aggregation::text = 'sum'
                       ) AS total_reactions,
                       max(m.value) FILTER (
                           WHERE m.metric_key = 'views' AND m.aggregation::text = 'sum'
                       ) AS total_views,
                       max(m.value) FILTER (
                           WHERE m.metric_key = 'reactions' AND m.aggregation::text = 'median'
                       ) AS median_reactions,
                       max(m.value) FILTER (
                           WHERE m.metric_key = 'views' AND m.aggregation::text = 'median'
                       ) AS median_views,
                       max(m.sample_size) AS sample_size,
                       min(m.coverage) AS coverage,
                       CASE max(CASE m.quality::text
                           WHEN 'exact' THEN 0
                           WHEN 'rounded' THEN 1
                           WHEN 'estimated' THEN 2
                           WHEN 'unknown' THEN 3
                           WHEN 'degraded' THEN 4
                           WHEN 'suspected_reset' THEN 5
                           ELSE 6
                       END)
                           WHEN 0 THEN 'exact'
                           WHEN 1 THEN 'rounded'
                           WHEN 2 THEN 'estimated'
                           WHEN 3 THEN 'unknown'
                           WHEN 4 THEN 'degraded'
                           WHEN 5 THEN 'suspected_reset'
                           ELSE 'invalid'
                       END AS quality,
                       min(m.as_of) AS as_of
                FROM analytics.institution_period_metrics m
                WHERE m.dataset_revision_id = :revision
                  AND m.period_key = :period
                  AND m.metric_key IN ('views', 'reactions')
                  AND ((:platform = 'all' AND m.platform IS NULL)
                       OR m.platform::text = :platform)
                GROUP BY m.institution_id
            )
            SELECT i.id AS institution_id,
                   alias.legacy_id,
                   i.canonical_name,
                   i.short_name,
                   metrics.total_reactions,
                   metrics.total_views,
                   metrics.median_reactions,
                   metrics.median_views,
                   metrics.sample_size,
                   metrics.coverage,
                   metrics.quality,
                   metrics.as_of
            FROM catalog.legacy_entity_alias alias
            JOIN catalog.institution i ON i.id = alias.target_uuid
            LEFT JOIN metrics ON metrics.institution_id = i.id
            WHERE alias.entity_type = 'institutions' AND alias.legacy_id = :legacyId
            """;

    static final String PUBLICATION_SQL = """
            SELECT p.id AS publication_id,
                   alias.legacy_id,
                   alias.entity_type,
                   account.institution_id,
                   p.published_at,
                   p.publication_type,
                   p.deleted_at,
                   account.platform::text AS platform,
                   latest.views_count,
                   latest.views_observed_at,
                   latest.views_quality::text AS views_quality,
                   latest.reactions_count,
                   latest.reactions_observed_at,
                   latest.reactions_quality::text AS reactions_quality,
                   latest.comments_count,
                   latest.comments_observed_at,
                   latest.comments_quality::text AS comments_quality,
                   latest.shares_count,
                   latest.shares_observed_at,
                   latest.shares_quality::text AS shares_quality,
                   latest.quality::text AS quality,
                   coalesce(latest.interval_uncertain, false) AS interval_uncertain,
                   coalesce(latest.synthetic, false) AS synthetic,
                   coalesce(
                       latest.history_completeness::text,
                       p.history_completeness::text
                   ) AS history_completeness,
                   latest.observed_at,
                   :revision AS dataset_revision_id
            FROM catalog.legacy_entity_alias alias
            JOIN ingest.publication p ON p.id = alias.target_uuid
            JOIN catalog.platform_account account ON account.id = p.primary_account_id
            LEFT JOIN analytics.publication_latest latest
              ON latest.publication_id = p.id
             AND latest.dataset_revision_id = :revision
            WHERE alias.entity_type = :legacyType
              AND alias.legacy_id = :legacyId
            """;

    private static final String PRE_ENGAGEMENT_INSTITUTION_COMPARISON_SQL = """
            WITH selected_cohort AS (
                SELECT cohort.id,
                       cohort.platform,
                       cohort.horizon_seconds,
                       cohort.as_of,
                       cohort.sample_size,
                       cohort.dataset_revision_id
                FROM analytics.comparison_cohort cohort
                JOIN analytics.projection_state state
                  ON state.projection_name = 'comparison'
                 AND state.status = 'ready'
                 AND state.dataset_revision_id = cohort.dataset_revision_id
                WHERE cohort.dataset_revision_id = :revision
                  AND cohort.platform::text = :platform
                  AND cohort.horizon_seconds = :horizonSeconds
                  AND (cohort.filter_definition->>'include_partial')::boolean = :includePartial
                ORDER BY cohort.as_of DESC, cohort.id
                LIMIT 1
            ), requested_legacy_ids AS (
                SELECT requested.value::bigint AS legacy_id,
                       requested.ordinality::integer AS selection_order
                FROM jsonb_array_elements_text(
                    CAST(:selectionLegacyIdsJson AS jsonb)
                ) WITH ORDINALITY AS requested(value, ordinality)
            ), default_institutions AS (
                SELECT account.institution_id,
                       min(lower(institution.canonical_name)) AS sort_name
                FROM selected_cohort cohort
                JOIN catalog.platform_account account
                  ON account.platform = cohort.platform
                 AND account.enabled
                JOIN catalog.institution institution ON institution.id = account.institution_id
                WHERE NOT EXISTS (SELECT 1 FROM requested_legacy_ids)
                GROUP BY account.institution_id
                ORDER BY sort_name, account.institution_id
                LIMIT :institutionLimit
            ), selected_institutions AS (
                SELECT requested.legacy_id,
                       requested.selection_order,
                       alias.target_uuid AS institution_id
                FROM requested_legacy_ids requested
                LEFT JOIN catalog.legacy_entity_alias alias
                  ON alias.entity_type = 'institutions'
                 AND alias.legacy_id = requested.legacy_id
                 AND EXISTS (
                     SELECT 1
                     FROM catalog.platform_account selected_account
                     WHERE selected_account.institution_id = alias.target_uuid
                       AND selected_account.platform::text = :platform
                       AND selected_account.enabled
                 )
                UNION ALL
                SELECT alias.legacy_id,
                       (row_number() OVER (
                           ORDER BY selected.sort_name, selected.institution_id
                       ))::integer AS selection_order,
                       selected.institution_id
                FROM default_institutions selected
                JOIN catalog.legacy_entity_alias alias
                  ON alias.entity_type = 'institutions'
                 AND alias.target_uuid = selected.institution_id
            )
            SELECT cohort.id AS cohort_id,
                   cohort.platform::text AS platform,
                   cohort.horizon_seconds,
                   cohort.as_of,
                   cohort.sample_size AS cohort_sample_size,
                   cohort.dataset_revision_id,
                   institution.id AS selection_id,
                   'institutions' AS selection_type,
                   selected.legacy_id AS selection_legacy_id,
                   coalesce(institution.short_name, institution.canonical_name) AS selection_label,
                   institution.id AS institution_id,
                   selected.legacy_id,
                   institution.canonical_name,
                   institution.short_name,
                   point.hour_offset,
                   point.value,
                   point.sample_size,
                   point.coverage,
                   point.quality::text AS quality
            FROM selected_institutions selected
            LEFT JOIN selected_cohort cohort ON true
            LEFT JOIN catalog.institution institution ON institution.id = selected.institution_id
            LEFT JOIN analytics.comparison_metric_point point
              ON point.cohort_id = cohort.id
             AND point.institution_id = selected.institution_id
             AND point.metric_key::text = :metric
             AND point.aggregation::text = :aggregation
            ORDER BY selected.selection_order, point.hour_offset
            """;

    private static final String PRE_ENGAGEMENT_CHANNEL_COMPARISON_SQL = """
            WITH selected_cohort AS (
                SELECT cohort.id,
                       cohort.platform,
                       cohort.horizon_seconds,
                       cohort.as_of,
                       cohort.sample_size,
                       cohort.dataset_revision_id,
                       (cohort.filter_definition->>'required_start_hour')::integer
                           AS required_start_hour
                FROM analytics.comparison_cohort cohort
                JOIN analytics.projection_state state
                  ON state.projection_name = 'comparison'
                 AND state.status = 'ready'
                 AND state.dataset_revision_id = cohort.dataset_revision_id
                WHERE cohort.dataset_revision_id = :revision
                  AND cohort.platform::text = :platform
                  AND cohort.horizon_seconds = :horizonSeconds
                  AND (cohort.filter_definition->>'include_partial')::boolean = :includePartial
                ORDER BY cohort.as_of DESC, cohort.id
                LIMIT 1
            ), requested_legacy_ids AS (
                SELECT requested.value::bigint AS legacy_id,
                       requested.ordinality::integer AS selection_order
                FROM jsonb_array_elements_text(
                    CAST(:selectionLegacyIdsJson AS jsonb)
                ) WITH ORDINALITY AS requested(value, ordinality)
            ), eligible_channels AS (
                SELECT channel_alias.legacy_id,
                       account.id AS selection_id,
                       account.institution_id,
                       coalesce(
                           nullif(account.current_title, ''),
                           CASE WHEN nullif(account.current_username, '') IS NOT NULL
                               THEN '@' || account.current_username END,
                           institution.short_name,
                           institution.canonical_name
                       ) AS selection_label,
                       lower(coalesce(
                           nullif(account.current_title, ''),
                           nullif(account.current_username, ''),
                           institution.short_name,
                           institution.canonical_name
                       )) AS sort_name
                FROM selected_cohort cohort
                JOIN catalog.platform_account account
                  ON account.platform = cohort.platform
                 AND account.enabled
                JOIN catalog.legacy_entity_alias channel_alias
                  ON channel_alias.entity_type = 'channels'
                 AND channel_alias.target_uuid = account.id
                JOIN catalog.institution institution ON institution.id = account.institution_id
                WHERE NOT EXISTS (SELECT 1 FROM requested_legacy_ids)
                GROUP BY channel_alias.legacy_id, account.id, account.institution_id,
                         account.current_title, account.current_username,
                         institution.short_name, institution.canonical_name
            ), default_channels AS (
                SELECT eligible.legacy_id,
                       eligible.selection_id,
                       eligible.institution_id,
                       eligible.selection_label,
                       (row_number() OVER (
                           ORDER BY eligible.sort_name, eligible.selection_id
                       ))::integer AS selection_order
                FROM eligible_channels eligible
                ORDER BY eligible.sort_name, eligible.selection_id
                LIMIT :institutionLimit
            ), selected_channels AS (
                SELECT requested.legacy_id,
                       requested.selection_order,
                       account.id AS selection_id,
                       account.institution_id,
                       coalesce(
                           nullif(account.current_title, ''),
                           CASE WHEN nullif(account.current_username, '') IS NOT NULL
                               THEN '@' || account.current_username END,
                           institution.short_name,
                           institution.canonical_name
                       ) AS selection_label
                FROM requested_legacy_ids requested
                LEFT JOIN catalog.legacy_entity_alias channel_alias
                  ON channel_alias.entity_type = 'channels'
                 AND channel_alias.legacy_id = requested.legacy_id
                LEFT JOIN catalog.platform_account account
                  ON account.id = channel_alias.target_uuid
                 AND account.platform::text = :platform
                 AND account.enabled
                LEFT JOIN catalog.institution institution ON institution.id = account.institution_id
                UNION ALL
                SELECT default_channel.legacy_id,
                       default_channel.selection_order,
                       default_channel.selection_id,
                       default_channel.institution_id,
                       default_channel.selection_label
                FROM default_channels default_channel
            ), cohort_hourly AS (
                SELECT cohort.id AS cohort_id,
                       hourly.platform_account_id,
                       hourly.publication_id,
                       hourly.hour_offset,
                       hourly.views_count,
                       hourly.reactions_count,
                       hourly.comments_count,
                       hourly.shares_count,
                       hourly.quality
                FROM selected_cohort cohort
                JOIN analytics.comparison_cohort_member member
                  ON member.cohort_id = cohort.id
                JOIN analytics.publication_hourly hourly
                  ON hourly.publication_id = member.publication_id
                 AND hourly.dataset_revision_id = cohort.dataset_revision_id
                 AND hourly.hour_offset >= cohort.required_start_hour
                 AND hourly.hour_offset <= cohort.horizon_seconds / 3600
            ), channel_sizes AS (
                SELECT hourly.cohort_id,
                       hourly.platform_account_id,
                       count(DISTINCT hourly.publication_id)::integer AS channel_cohort_size
                FROM cohort_hourly hourly
                GROUP BY hourly.cohort_id, hourly.platform_account_id
            ), channel_hourly AS (
                SELECT cohort.id AS cohort_id,
                       cohort.as_of,
                       cohort.sample_size AS cohort_sample_size,
                       selected.selection_order,
                       selected.selection_id,
                       selected.legacy_id AS selection_legacy_id,
                       selected.selection_label,
                       institution.id AS institution_id,
                       institution_alias.legacy_id,
                       institution.canonical_name,
                       institution.short_name,
                       coalesce(size.channel_cohort_size, 0) AS channel_cohort_size,
                       hourly.publication_id,
                       hourly.hour_offset,
                       CASE :metric
                           WHEN 'views' THEN hourly.views_count
                           WHEN 'reactions' THEN hourly.reactions_count
                           WHEN 'comments' THEN hourly.comments_count
                           WHEN 'shares' THEN hourly.shares_count
                       END AS metric_value,
                       hourly.quality::text AS quality
                FROM selected_channels selected
                LEFT JOIN selected_cohort cohort ON true
                LEFT JOIN catalog.institution institution
                  ON institution.id = selected.institution_id
                LEFT JOIN catalog.legacy_entity_alias institution_alias
                  ON institution_alias.entity_type = 'institutions'
                 AND institution_alias.target_uuid = institution.id
                LEFT JOIN channel_sizes size
                  ON size.cohort_id = cohort.id
                 AND size.platform_account_id = selected.selection_id
                LEFT JOIN cohort_hourly hourly
                  ON hourly.cohort_id = cohort.id
                 AND hourly.platform_account_id = selected.selection_id
            ), grouped AS (
                SELECT cohort_id,
                       as_of,
                       cohort_sample_size,
                       selection_order,
                       selection_id,
                       selection_legacy_id,
                       selection_label,
                       institution_id,
                       legacy_id,
                       canonical_name,
                       short_name,
                       channel_cohort_size,
                       hour_offset,
                       count(publication_id)::integer AS publication_count,
                       count(metric_value)::integer AS sample_size,
                       sum(metric_value)::numeric AS sum_value,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY metric_value)
                           FILTER (WHERE metric_value IS NOT NULL)::numeric AS median_value,
                       max(CASE quality
                           WHEN 'exact' THEN 0
                           WHEN 'rounded' THEN 1
                           WHEN 'estimated' THEN 2
                           WHEN 'unknown' THEN 3
                           WHEN 'degraded' THEN 4
                           WHEN 'suspected_reset' THEN 5
                           ELSE 6
                       END) FILTER (WHERE metric_value IS NOT NULL) AS worst_quality
                FROM channel_hourly
                GROUP BY cohort_id, as_of, cohort_sample_size, selection_order,
                         selection_id, selection_legacy_id, selection_label,
                         institution_id, legacy_id, canonical_name, short_name,
                         channel_cohort_size, hour_offset
            )
            SELECT cohort_id,
                   :platform AS platform,
                   :horizonSeconds AS horizon_seconds,
                   as_of,
                   cohort_sample_size,
                   :revision AS dataset_revision_id,
                   selection_id,
                   'channels' AS selection_type,
                   selection_legacy_id,
                   selection_label,
                   institution_id,
                   legacy_id,
                   canonical_name,
                   short_name,
                   hour_offset,
                   CASE :aggregation
                       WHEN 'sum' THEN sum_value
                       ELSE round(median_value, 0)
                   END AS value,
                   sample_size,
                   CASE WHEN channel_cohort_size = 0 THEN 0::numeric
                        ELSE round(sample_size::numeric / channel_cohort_size, 6)
                   END AS coverage,
                   CASE worst_quality
                       WHEN 0 THEN 'exact'
                       WHEN 1 THEN 'rounded'
                       WHEN 2 THEN 'estimated'
                       WHEN 3 THEN 'unknown'
                       WHEN 4 THEN 'degraded'
                       WHEN 5 THEN 'suspected_reset'
                       WHEN 6 THEN 'invalid'
                       ELSE 'unknown'
                   END AS quality
            FROM grouped
            ORDER BY selection_order, hour_offset
            """;

    static final String INSTITUTION_COMPARISON_SQL = ComparisonSql.INSTITUTIONS;
    static final String CHANNEL_COMPARISON_SQL = ComparisonSql.CHANNELS;
    static final String COMPARISON_SQL = INSTITUTION_COMPARISON_SQL;

    static final String ACCOUNT_SQL = """
            WITH account_metrics AS (
                SELECT latest.platform_account_id,
                       count(*) AS publication_count,
                       max(latest.observed_at) AS latest_observed_at
                FROM analytics.publication_latest latest
                WHERE latest.dataset_revision_id = :revision
                GROUP BY latest.platform_account_id
            ), account_aliases AS (
                SELECT alias.target_uuid,
                       min(alias.legacy_id) FILTER (
                           WHERE alias.entity_type = 'channels'
                       ) AS channel_legacy_id,
                       min(alias.legacy_id) FILTER (
                           WHERE alias.entity_type = 'platform_accounts'
                       ) AS platform_account_legacy_id
                FROM catalog.legacy_entity_alias alias
                WHERE alias.entity_type IN ('channels', 'platform_accounts')
                GROUP BY alias.target_uuid
            )
            SELECT account.id AS account_id,
                   account_alias.legacy_id,
                   account_alias.entity_type,
                   aliases.channel_legacy_id,
                   aliases.platform_account_legacy_id,
                   institution.id AS institution_id,
                   institution_alias.legacy_id AS institution_legacy_id,
                   institution.canonical_name,
                   institution.short_name,
                   account.platform::text AS platform,
                   account.canonical_external_id,
                   account.current_username,
                   account.current_title,
                   account.current_url,
                   account.access_mode::text AS access_mode,
                   account.enabled,
                   coalesce(metrics.publication_count, 0) AS publication_count,
                   metrics.latest_observed_at
            FROM catalog.legacy_entity_alias account_alias
            JOIN catalog.platform_account account ON account.id = account_alias.target_uuid
            JOIN catalog.institution institution ON institution.id = account.institution_id
            JOIN catalog.legacy_entity_alias institution_alias
              ON institution_alias.target_uuid = institution.id
             AND institution_alias.entity_type = 'institutions'
            LEFT JOIN account_aliases aliases ON aliases.target_uuid = account.id
            LEFT JOIN account_metrics metrics ON metrics.platform_account_id = account.id
            WHERE account_alias.entity_type = :legacyType
              AND account_alias.legacy_id = :legacyId
            """;

    private final JdbcClient jdbcClient;

    public JdbcProjectionQueryRepository(JdbcClient jdbcClient) {
        this.jdbcClient = jdbcClient;
    }

    @Override
    public List<OverviewCard> findOverview(
            OverviewQuery query,
            int fetchLimit,
            UUID afterEntityId,
            long datasetRevision
    ) {
        List<OverviewSqlRow> rows = jdbcClient.sql(OVERVIEW_SQL)
                .param("revision", datasetRevision)
                .param("period", query.period().databaseValue())
                .param("platform", query.platform().databaseValue())
                .param("search", query.search())
                .param("sort", query.sort())
                .param("direction", query.direction())
                .param("afterId", afterEntityId, Types.OTHER)
                .param("fetchLimit", fetchLimit)
                .query((resultSet, rowNumber) -> overviewRow(resultSet))
                .list();
        Map<UUID, OverviewAccumulator> grouped = new LinkedHashMap<>();
        for (OverviewSqlRow row : rows) {
            OverviewAccumulator accumulator = grouped.computeIfAbsent(
                    row.card().entityId(), ignored -> new OverviewAccumulator(row.card())
            );
            if (row.account() != null) {
                accumulator.accounts().add(row.account());
            }
        }
        return grouped.values().stream().map(OverviewAccumulator::build).toList();
    }

    @Override
    public Optional<InstitutionView> findInstitution(
            long legacyId,
            Platform platform,
            PeriodKey period,
            long datasetRevision
    ) {
        return jdbcClient.sql(INSTITUTION_SQL)
                .param("revision", datasetRevision)
                .param("period", period.databaseValue())
                .param("platform", platform.databaseValue())
                .param("legacyId", legacyId)
                .query((resultSet, rowNumber) -> new InstitutionView(
                        institution(resultSet), platform, period, metrics(resultSet, datasetRevision)
                ))
                .optional();
    }

    @Override
    public Optional<PublicationView> findPublication(
            long legacyId,
            LegacyEntityType legacyEntityType,
            long datasetRevision
    ) {
        return jdbcClient.sql(PUBLICATION_SQL)
                .param("legacyType", legacyEntityType.databaseValue())
                .param("legacyId", legacyId)
                .param("revision", datasetRevision)
                .query((resultSet, rowNumber) -> publication(resultSet, legacyEntityType))
                .optional();
    }

    @Override
    public ActivityRatingResult findActivityRating(
            ActivityRatingQuery query,
            int entityLimit,
            long datasetRevision
    ) {
        String entitySql = query.platform() == Platform.TELEGRAM
                ? ActivityRatingSql.TELEGRAM_ENTITIES
                : ActivityRatingSql.PLATFORM_ENTITIES;
        String publicationSql = query.platform() == Platform.TELEGRAM
                ? ActivityRatingSql.TELEGRAM_PUBLICATIONS
                : ActivityRatingSql.PLATFORM_PUBLICATIONS;
        List<ActivityRatingEntity> fetchedEntities = jdbcClient.sql(entitySql)
                .param("revision", datasetRevision)
                .param("period", query.period().databaseValue())
                .param("platform", query.platform().databaseValue())
                .param("channelSort", query.channelSort())
                .param("channelDirection", query.channelDirection())
                .param("entityFetchLimit", entityLimit + 1)
                .query((resultSet, rowNumber) -> activityRatingEntity(resultSet))
                .list();
        boolean truncated = fetchedEntities.size() > entityLimit;
        List<ActivityRatingEntity> entities = List.copyOf(fetchedEntities.subList(
                0, Math.min(entityLimit, fetchedEntities.size())
        ));
        List<ActivityRatingPublication> publications = jdbcClient.sql(publicationSql)
                .param("revision", datasetRevision)
                .param("period", query.period().databaseValue())
                .param("platform", query.platform().databaseValue())
                .param("postSort", query.postSort())
                .param("postDirection", query.postDirection())
                .query((resultSet, rowNumber) -> activityRatingPublication(resultSet))
                .list();
        return new ActivityRatingResult(entities, publications, truncated);
    }

    @Override
    public Optional<ComparisonView> findComparison(
            Platform platform,
            int horizonHours,
            boolean includePartial,
            String metric,
            String aggregation,
            int institutionLimit,
            ComparisonSelection selection,
            long datasetRevision
    ) {
        String sql = selection.type() == ComparisonSelectionType.CHANNELS
                ? CHANNEL_COMPARISON_SQL
                : INSTITUTION_COMPARISON_SQL;
        List<ComparisonRow> rows = jdbcClient.sql(sql)
                .param("revision", datasetRevision)
                .param("platform", platform.databaseValue())
                .param("horizonSeconds", Math.multiplyExact(horizonHours, 3600))
                .param("includePartial", includePartial)
                .param("metric", metric)
                .param("aggregation", aggregation)
                .param("institutionLimit", institutionLimit)
                .param("selectionLegacyIdsJson", legacyIdsJson(selection.legacyIds()))
                .query((resultSet, rowNumber) -> comparisonRow(resultSet))
                .list();
        if (rows.isEmpty()) {
            return Optional.empty();
        }

        ComparisonRow first = rows.getFirst();
        if (first.cohortId() == null) {
            return Optional.empty();
        }

        Map<UUID, ComparisonAccumulator> grouped = new LinkedHashMap<>();
        for (ComparisonRow row : rows) {
            if (!row.mapped()) {
                continue;
            }
            ComparisonAccumulator accumulator = grouped.computeIfAbsent(
                    row.selectionId(), ignored -> new ComparisonAccumulator(
                            row.selectionId(), row.selectionType(), row.requestedLegacyId(),
                            row.selectionLabel(), row.institution(), row.primaryCohortSize(),
                            row.engagementCohortSize()
                    )
            );
            if (row.point() != null) {
                accumulator.points().add(row.point());
            }
            if (row.engagementPoint() != null) {
                accumulator.engagementPoints().add(row.engagementPoint());
            }
        }
        List<ComparisonSeries> series = grouped.values().stream()
                .map(accumulator -> new ComparisonSeries(
                        accumulator.selectionId(), accumulator.selectionType(),
                        accumulator.selectionLegacyId(), accumulator.selectionLabel(),
                        accumulator.institution(), accumulator.primaryCohortSize(),
                        accumulator.engagementCohortSize(), accumulator.points(),
                        accumulator.engagementPoints()
                ))
                .toList();
        return Optional.of(new ComparisonView(
                first.cohortId(), platform, horizonHours, includePartial, metric, aggregation,
                selection.type(), first.cohortSampleSize(), series, datasetRevision, first.asOf()
        ));
    }

    @Override
    public Optional<AccountView> findAccount(
            long legacyId,
            LegacyEntityType legacyEntityType,
            long datasetRevision
    ) {
        return jdbcClient.sql(ACCOUNT_SQL)
                .param("revision", datasetRevision)
                .param("legacyType", legacyEntityType.databaseValue())
                .param("legacyId", legacyId)
                .query((resultSet, rowNumber) -> new AccountView(
                        resultSet.getObject("account_id", UUID.class),
                        resultSet.getLong("legacy_id"),
                        legacyEntityType,
                        nullableLong(resultSet, "channel_legacy_id"),
                        nullableLong(resultSet, "platform_account_legacy_id"),
                        new InstitutionIdentity(
                                resultSet.getObject("institution_id", UUID.class),
                                resultSet.getLong("institution_legacy_id"),
                                resultSet.getString("canonical_name"),
                                resultSet.getString("short_name")
                        ),
                        Platform.fromApiValue(resultSet.getString("platform")),
                        resultSet.getString("canonical_external_id"),
                        resultSet.getString("current_username"),
                        resultSet.getString("current_title"),
                        resultSet.getString("current_url"),
                        resultSet.getString("access_mode"),
                        resultSet.getBoolean("enabled"),
                        resultSet.getLong("publication_count"),
                        instant(resultSet, "latest_observed_at"),
                        datasetRevision,
                        instant(resultSet, "latest_observed_at")
                ))
                .optional();
    }

    private static OverviewSqlRow overviewRow(ResultSet resultSet) throws SQLException {
        InstitutionIdentity institution = new InstitutionIdentity(
                resultSet.getObject("institution_id", UUID.class),
                resultSet.getLong("institution_legacy_id"),
                resultSet.getString("canonical_name"),
                resultSet.getString("short_name")
        );
        OverviewCard card = new OverviewCard(
                resultSet.getObject("entity_id", UUID.class),
                resultSet.getString("entity_type"),
                resultSet.getLong("legacy_id"),
                resultSet.getString("legacy_route"),
                institution,
                Platform.fromApiValue(resultSet.getString("platform")),
                PeriodKey.fromApiValue(resultSet.getString("period_key")),
                List.of(),
                resultSet.getInt("account_count"),
                resultSet.getInt("enabled_account_count"),
                resultSet.getInt("connected_platform_count"),
                nullableLong(resultSet, "subscriber_count"),
                instant(resultSet, "last_checked_at"),
                resultSet.getString("last_error_code"),
                resultSet.getString("status_code"),
                resultSet.getObject("rating_rank", Integer.class),
                resultSet.getObject("rating_score", BigDecimal.class),
                resultSet.getString("rating_period"),
                instant(resultSet, "rating_fetched_at"),
                nullableLong(resultSet, "total_publication_count"),
                nullableLong(resultSet, "activity_publication_count"),
                nullableLong(resultSet, "new_publication_count"),
                overviewMetric(resultSet, "views"),
                overviewMetric(resultSet, "reactions"),
                overviewMetric(resultSet, "comments"),
                overviewMetric(resultSet, "shares"),
                resultSet.getLong("dataset_revision_id"),
                instant(resultSet, "as_of")
        );
        UUID accountId = resultSet.getObject("account_id", UUID.class);
        OverviewAccount account = accountId == null ? null : new OverviewAccount(
                accountId,
                nullableLong(resultSet, "account_legacy_id"),
                resultSet.getString("account_legacy_route"),
                Platform.fromApiValue(resultSet.getString("account_platform")),
                resultSet.getString("account_external_id"),
                resultSet.getString("account_username"),
                resultSet.getString("account_title"),
                resultSet.getString("account_url"),
                resultSet.getString("account_access_mode"),
                resultSet.getBoolean("account_enabled"),
                nullableLong(resultSet, "account_subscriber_count"),
                resultSet.getString("account_subscriber_display"),
                instant(resultSet, "account_subscriber_observed_at"),
                instant(resultSet, "account_latest_poll_started_at"),
                instant(resultSet, "account_latest_poll_completed_at"),
                resultSet.getString("account_latest_poll_status"),
                resultSet.getString("account_latest_error_code")
        );
        return new OverviewSqlRow(card, account);
    }

    private static OverviewMetric overviewMetric(ResultSet resultSet, String metric)
            throws SQLException {
        return new OverviewMetric(
                resultSet.getObject("total_" + metric, BigDecimal.class),
                resultSet.getObject("median_" + metric, BigDecimal.class),
                resultSet.getObject("previous_total_" + metric, BigDecimal.class),
                resultSet.getObject("previous_median_" + metric, BigDecimal.class),
                resultSet.getObject("delta_total_" + metric, BigDecimal.class),
                resultSet.getObject("delta_median_" + metric, BigDecimal.class)
        );
    }

    private static InstitutionIdentity institution(ResultSet resultSet) throws SQLException {
        return new InstitutionIdentity(
                resultSet.getObject("institution_id", UUID.class),
                resultSet.getLong("legacy_id"),
                resultSet.getString("canonical_name"),
                resultSet.getString("short_name")
        );
    }

    private static MetricSet metrics(ResultSet resultSet, long datasetRevision) throws SQLException {
        Integer sampleSize = resultSet.getObject("sample_size", Integer.class);
        return new MetricSet(
                resultSet.getObject("total_reactions", BigDecimal.class),
                resultSet.getObject("total_views", BigDecimal.class),
                resultSet.getObject("median_reactions", BigDecimal.class),
                resultSet.getObject("median_views", BigDecimal.class),
                sampleSize == null ? 0 : sampleSize,
                resultSet.getObject("coverage", BigDecimal.class),
                resultSet.getString("quality"),
                instant(resultSet, "as_of"),
                datasetRevision
        );
    }

    private static PublicationView publication(
            ResultSet resultSet,
            LegacyEntityType legacyEntityType
    ) throws SQLException {
        PublicationIdentity identity = new PublicationIdentity(
                resultSet.getObject("publication_id", UUID.class),
                resultSet.getLong("legacy_id"),
                legacyEntityType,
                resultSet.getObject("institution_id", UUID.class),
                instant(resultSet, "published_at"),
                resultSet.getString("publication_type"),
                instant(resultSet, "deleted_at")
        );
        return new PublicationView(
                identity,
                Platform.fromApiValue(resultSet.getString("platform")),
                counter(resultSet, "views"),
                counter(resultSet, "reactions"),
                counter(resultSet, "comments"),
                counter(resultSet, "shares"),
                resultSet.getString("quality"),
                resultSet.getBoolean("interval_uncertain"),
                resultSet.getBoolean("synthetic"),
                resultSet.getString("history_completeness"),
                instant(resultSet, "observed_at"),
                resultSet.getLong("dataset_revision_id")
        );
    }

    private static CounterMetric counter(ResultSet resultSet, String metric) throws SQLException {
        return new CounterMetric(
                resultSet.getObject(metric + "_count", Long.class),
                instant(resultSet, metric + "_observed_at"),
                resultSet.getString(metric + "_quality")
        );
    }

    private static ComparisonRow comparisonRow(ResultSet resultSet) throws SQLException {
        long requestedLegacyId = resultSet.getLong("selection_legacy_id");
        UUID selectionId = resultSet.getObject("selection_id", UUID.class);
        String selectionType = resultSet.getString("selection_type");
        String selectionLabel = resultSet.getString("selection_label");
        UUID institutionId = resultSet.getObject("institution_id", UUID.class);
        Integer hourOffset = resultSet.getObject("hour_offset", Integer.class);
        boolean mapped = selectionId != null && institutionId != null;
        if (!mapped) {
            return new ComparisonRow(
                    resultSet.getObject("cohort_id", UUID.class),
                    resultSet.getInt("cohort_sample_size"),
                    instant(resultSet, "as_of"),
                    requestedLegacyId,
                    mapped,
                    selectionId,
                    ComparisonSelectionType.valueOf(selectionType == null
                            ? "INSTITUTIONS" : selectionType.toUpperCase(java.util.Locale.ROOT)),
                    selectionLabel,
                    null,
                    0,
                    0,
                    null,
                    null
            );
        }
        InstitutionIdentity institution = new InstitutionIdentity(
                institutionId,
                resultSet.getLong("legacy_id"),
                resultSet.getString("canonical_name"),
                resultSet.getString("short_name")
        );
        ComparisonPoint point = hourOffset == null ? null : new ComparisonPoint(
                resultSet.getInt("hour_offset"),
                resultSet.getObject("value", BigDecimal.class),
                resultSet.getInt("sample_size"),
                resultSet.getObject("coverage", BigDecimal.class),
                resultSet.getString("quality")
        );
        ComparisonPoint engagementPoint = hourOffset == null ? null : new ComparisonPoint(
                resultSet.getInt("hour_offset"),
                resultSet.getObject("engagement_value", BigDecimal.class),
                resultSet.getInt("engagement_sample_size"),
                resultSet.getObject("engagement_coverage", BigDecimal.class),
                resultSet.getString("engagement_quality")
        );
        return new ComparisonRow(
                resultSet.getObject("cohort_id", UUID.class),
                resultSet.getInt("cohort_sample_size"),
                instant(resultSet, "as_of"),
                requestedLegacyId,
                true,
                selectionId,
                ComparisonSelectionType.valueOf(
                        selectionType.toUpperCase(java.util.Locale.ROOT)
                ),
                selectionLabel,
                institution,
                resultSet.getInt("primary_cohort_size"),
                resultSet.getInt("engagement_cohort_size"),
                point,
                engagementPoint
        );
    }

    private static String legacyIdsJson(List<Long> legacyIds) {
        return legacyIds.stream()
                .map(String::valueOf)
                .collect(java.util.stream.Collectors.joining(",", "[", "]"));
    }

    private static ActivityRatingEntity activityRatingEntity(ResultSet resultSet)
            throws SQLException {
        return new ActivityRatingEntity(
                resultSet.getObject("entity_id", UUID.class),
                resultSet.getString("entity_type"),
                resultSet.getLong("legacy_id"),
                resultSet.getString("legacy_route"),
                resultSet.getObject("institution_id", UUID.class),
                nullableLong(resultSet, "institution_legacy_id"),
                resultSet.getString("canonical_name"),
                resultSet.getString("short_name"),
                resultSet.getString("username"),
                resultSet.getString("title"),
                resultSet.getInt("publication_count"),
                resultSet.getObject("average_reactions", BigDecimal.class),
                resultSet.getObject("average_views", BigDecimal.class),
                resultSet.getLong("total_reactions"),
                nullableLong(resultSet, "total_views"),
                nullableLong(resultSet, "total_comments"),
                nullableLong(resultSet, "total_shares"),
                nullableLong(resultSet, "total_interactions"),
                resultSet.getObject("engagement_rate", BigDecimal.class),
                nullableLong(resultSet, "subscriber_count")
        );
    }

    private static ActivityRatingPublication activityRatingPublication(ResultSet resultSet)
            throws SQLException {
        return new ActivityRatingPublication(
                resultSet.getObject("publication_id", UUID.class),
                nullableLong(resultSet, "legacy_id"),
                resultSet.getString("legacy_type"),
                resultSet.getString("legacy_route"),
                resultSet.getObject("institution_id", UUID.class),
                resultSet.getLong("institution_legacy_id"),
                resultSet.getString("institution_canonical_name"),
                resultSet.getString("institution_short_name"),
                resultSet.getObject("account_id", UUID.class),
                nullableLong(resultSet, "account_legacy_id"),
                resultSet.getString("account_username"),
                resultSet.getString("account_title"),
                resultSet.getString("external_id"),
                resultSet.getString("public_url"),
                instant(resultSet, "published_at"),
                instant(resultSet, "deleted_at"),
                resultSet.getBoolean("joint"),
                resultSet.getInt("additional_author_count"),
                resultSet.getBoolean("repost"),
                nullableLong(resultSet, "views"),
                nullableLong(resultSet, "reactions"),
                nullableLong(resultSet, "comments"),
                nullableLong(resultSet, "shares"),
                nullableLong(resultSet, "interactions"),
                resultSet.getObject("subscriber_share", BigDecimal.class),
                resultSet.getObject("view_share", BigDecimal.class)
        );
    }

    private static Instant instant(ResultSet resultSet, String column) throws SQLException {
        OffsetDateTime value = resultSet.getObject(column, OffsetDateTime.class);
        return value == null ? null : value.toInstant();
    }

    private static Long nullableLong(ResultSet resultSet, String column) throws SQLException {
        return resultSet.getObject(column, Long.class);
    }

    private record ComparisonRow(
            UUID cohortId,
            int cohortSampleSize,
            Instant asOf,
            long requestedLegacyId,
            boolean mapped,
            UUID selectionId,
            ComparisonSelectionType selectionType,
            String selectionLabel,
            InstitutionIdentity institution,
            int primaryCohortSize,
            int engagementCohortSize,
            ComparisonPoint point,
            ComparisonPoint engagementPoint
    ) {
    }

    private record OverviewSqlRow(OverviewCard card, OverviewAccount account) {
    }

    private record OverviewAccumulator(OverviewCard card, List<OverviewAccount> accounts) {
        private OverviewAccumulator(OverviewCard card) {
            this(card, new ArrayList<>());
        }

        private OverviewCard build() {
            return card.withAccounts(accounts);
        }
    }

    private record ComparisonAccumulator(
            UUID selectionId,
            ComparisonSelectionType selectionType,
            long selectionLegacyId,
            String selectionLabel,
            InstitutionIdentity institution,
            int primaryCohortSize,
            int engagementCohortSize,
            List<ComparisonPoint> points,
            List<ComparisonPoint> engagementPoints
    ) {
        private ComparisonAccumulator(
                UUID selectionId,
                ComparisonSelectionType selectionType,
                long selectionLegacyId,
                String selectionLabel,
                InstitutionIdentity institution,
                int primaryCohortSize,
                int engagementCohortSize
        ) {
            this(selectionId, selectionType, selectionLegacyId, selectionLabel,
                    institution, primaryCohortSize, engagementCohortSize,
                    new ArrayList<>(), new ArrayList<>());
        }
    }
}
