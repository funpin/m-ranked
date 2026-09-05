package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class ProjectionSqlTest {
    @Test
    void overviewIsRevisionPinnedAndKeysetReady() {
        assertThat(JdbcProjectionQueryRepository.OVERVIEW_SQL)
                .contains("analytics.legacy_overview_card")
                .contains("card.dataset_revision_id = :revision")
                .contains("analytics.legacy_overview_account")
                .contains("CAST(:afterId AS uuid)")
                .contains("row_number() OVER (ORDER BY")
                .contains("WHEN 'm_rating' THEN card.rating_rank::numeric")
                .contains("WHEN 'posts' THEN card.new_publication_count::numeric")
                .contains("END ASC NULLS LAST")
                .contains("END DESC NULLS LAST")
                .contains("LIMIT :fetchLimit")
                .doesNotContain("metric_snapshot");
    }

    @Test
    void detailQueriesResolveLegacyAliasesAndExactProjectionRevision() {
        assertThat(JdbcProjectionQueryRepository.INSTITUTION_SQL)
                .contains("alias.entity_type = 'institutions'")
                .contains("m.dataset_revision_id = :revision")
                .contains("m.metric_key IN ('views', 'reactions')")
                .contains("LEFT JOIN metrics ON metrics.institution_id = i.id");
        assertThat(JdbcProjectionQueryRepository.PUBLICATION_SQL)
                .contains("catalog.legacy_entity_alias")
                .contains("JOIN ingest.publication p ON p.id = alias.target_uuid")
                .contains("JOIN catalog.platform_account account ON account.id = p.primary_account_id")
                .contains("LEFT JOIN analytics.publication_latest latest")
                .contains("latest.dataset_revision_id = :revision")
                .contains("account.institution_id")
                .contains("account.platform::text AS platform")
                .contains("latest.history_completeness::text")
                .contains("p.history_completeness::text")
                .contains(":revision AS dataset_revision_id")
                .contains("latest.views_observed_at")
                .contains("latest.views_quality::text")
                .contains("coalesce(latest.interval_uncertain, false)")
                .contains("coalesce(latest.synthetic, false)")
                .doesNotContain("publication_metric_snapshot")
                .doesNotContain("raw_payload");
    }

    @Test
    void csvUsesForwardOnlyBoundedFetchOverTheProjection() {
        assertThat(JdbcPublicationCsvRowSource.EXPORT_SQL)
                .contains("analytics.publication_latest")
                .contains("latest.dataset_revision_id = ?")
                .doesNotContain("metric_snapshot");
        assertThat(JdbcPublicationCsvRowSource.FETCH_SIZE).isEqualTo(500);
    }

    @Test
    void parityQueriesAreSetBasedRevisionPinnedAndBounded() {
        assertThat(ActivityRatingSql.TELEGRAM_ENTITIES)
                .contains("analytics.publication_latest")
                .contains("latest.dataset_revision_id = revision.id")
                .contains("publication.published_at >= revision.cutoff")
                .contains("account.platform = 'telegram'")
                .contains("account.enabled")
                .contains("entity_type = 'channels'")
                .contains("NULLS FIRST")
                .contains("LIMIT :entityFetchLimit")
                .doesNotContain("publication_metric_snapshot")
                .doesNotContain("rating.rating_run");
        assertThat(ActivityRatingSql.PLATFORM_ENTITIES)
                .contains("latest.platform::text = :platform")
                .contains("sum(fact.interactions_count)")
                .contains("avg(fact.reactions_count::numeric)")
                .contains("NULLS LAST")
                .doesNotContain("publication_metric_snapshot");
        assertThat(ActivityRatingSql.TELEGRAM_PUBLICATIONS)
                .contains("latest.source_snapshot_refs ->> 'latest'")
                .contains("subscriber_share")
                .contains("LIMIT 50")
                .contains("NULLS FIRST")
                .doesNotContain("publication_metric_snapshot");
        assertThat(ActivityRatingSql.PLATFORM_PUBLICATIONS)
                .contains("publication.quality_flags -> 'joint_post'")
                .contains("publication.quality_flags -> 'legacy_is_joint'")
                .contains("-> 'additional_author_count'")
                .contains("-> 'legacy_additional_author_count'")
                .contains("joint_author")
                .contains("LIMIT 50")
                .contains("NULLS LAST")
                .doesNotContain("publication_metric_snapshot")
                .doesNotContain("rating.rating_run");

        assertThat(JdbcProjectionQueryRepository.INSTITUTION_COMPARISON_SQL)
                .contains("analytics.comparison_cohort")
                .contains("analytics.comparison_cohort_member")
                .contains("analytics.comparison_publication_hourly")
                .contains("state.projection_name = 'comparison'")
                .contains("state.status = 'ready'")
                .contains("cohort.dataset_revision_id = :revision")
                .contains("LIMIT :institutionLimit")
                .contains("jsonb_array_elements_text")
                .contains("WITH ORDINALITY")
                .contains("alias.entity_type = 'institutions'")
                .contains("FROM selected_institutions selected")
                .contains("primary_members AS")
                .contains("engagement_members AS")
                .contains("ORDER BY selected.selection_order, hour.hour_offset")
                .doesNotContain("migration.")
                .doesNotContain("analytics.comparison_metric_point")
                .doesNotContain("publication_metric_snapshot");

        assertThat(JdbcProjectionQueryRepository.CHANNEL_COMPARISON_SQL)
                .contains("analytics.comparison_cohort")
                .contains("analytics.comparison_cohort_member")
                .contains("analytics.comparison_publication_hourly")
                .contains("hourly.dataset_revision_id = cohort.dataset_revision_id")
                .contains("state.projection_name = 'comparison'")
                .contains("state.status = 'ready'")
                .contains("cohort.dataset_revision_id = :revision")
                .contains("LIMIT :institutionLimit")
                .contains("jsonb_array_elements_text")
                .contains("WITH ORDINALITY")
                .contains("channel_alias.entity_type = 'channels'")
                .contains("institution_alias.entity_type = 'institutions'")
                .contains("primary_members AS")
                .contains("engagement_members AS")
                .contains("ORDER BY selected.selection_order, hour.hour_offset")
                .doesNotContain("migration.")
                .doesNotContain("publication_metric_snapshot")
                .doesNotContain("metric_snapshot");

        assertThat(JdbcProjectionQueryRepository.ACCOUNT_SQL)
                .contains("catalog.platform_account")
                .contains("catalog.legacy_entity_alias")
                .contains("WHERE alias.entity_type = 'channels'")
                .contains("WHERE alias.entity_type = 'platform_accounts'")
                .contains("analytics.publication_latest")
                .contains("latest.dataset_revision_id = :revision")
                .doesNotContain("account_metric_snapshot");
    }
}
