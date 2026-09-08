package org.mranked.analysis.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.OffsetDateTime;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

@EnabledIfEnvironmentVariable(named = "MRANKED_ANALYSIS_TEST_POSTGRES_URL", matches = ".+")
class JdbcAnalysisPostgresIntegrationTest {
    @Test
    void safePublicAdapterResolvesBothIdentitiesAndReadsManualEvidence() {
        // Dedicated disposable database: the fixture publication and its rebuilt
        // core revision are retained and must not leak into catalog/admin cleanup.
        String url = requiredEnvironment("MRANKED_ANALYSIS_TEST_POSTGRES_URL");
        JdbcClient owner = JdbcClient.create(dataSource(
                url,
                requiredEnvironment("MRANKED_ADMIN_TEST_OWNER_USERNAME"),
                requiredEnvironment("MRANKED_ADMIN_TEST_OWNER_PASSWORD")
        ));
        JdbcClient reader = JdbcClient.create(dataSource(
                url, "api_read", requiredEnvironment("MRANKED_QUERY_TEST_PASSWORD")
        ));
        UUID institution = UUID.randomUUID();
        UUID account = UUID.randomUUID();
        UUID publication = UUID.randomUUID();
        long legacyId = 9_800_000_000L
                + Math.floorMod(UUID.randomUUID().getLeastSignificantBits(), 100_000_000L);
        OffsetDateTime start = OffsetDateTime.now().minusMinutes(30);
        OffsetDateTime end = start.plusMinutes(10);

        owner.sql("INSERT INTO catalog.institution(id,canonical_name) VALUES (:id,:name)")
                .param("id", institution).param("name", "Analysis JDBC " + institution).update();
        owner.sql("""
                INSERT INTO catalog.platform_account(
                    id,institution_id,platform,canonical_external_id,access_mode
                ) VALUES (:id,:institution,'vk',:external,'public_web')
                """).param("id", account).param("institution", institution)
                .param("external", "analysis-jdbc-" + account).update();
        owner.sql("""
                INSERT INTO ingest.publication(
                    id,primary_account_id,published_at,discovered_at,
                    publication_type,history_completeness
                ) VALUES (:id,:account,now()-interval '1 hour',now(),'post','complete')
                """).param("id", publication).param("account", account).update();
        owner.sql("""
                INSERT INTO catalog.legacy_entity_alias(entity_type,legacy_id,target_uuid)
                VALUES ('posts',:legacy,:publication)
                """).param("legacy", legacyId).param("publication", publication).update();
        owner.sql("""
                SELECT analytics.create_manual_anomaly_signal(
                    :publication,'views','medium','operator_context',:start,:end,
                    '{"source":"integration"}'::jsonb,'jdbc-integration',
                    :correlation,:idempotency,:digest
                )
                """).param("publication", publication).param("start", start).param("end", end)
                .param("correlation", UUID.randomUUID()).param("idempotency", UUID.randomUUID())
                .param("digest", "a".repeat(64)).query(String.class).single();

        JdbcAnalysisQueryRepository repository = new JdbcAnalysisQueryRepository(reader);
        assertThat(repository.resolvePublication(publication.toString(), "posts"))
                .contains(publication);
        assertThat(repository.resolvePublication(Long.toString(legacyId), "posts"))
                .contains(publication);
        assertThat(repository.load(publication, 25, null)).satisfies(snapshot -> {
            assertThat(snapshot.publicationId()).isEqualTo(publication);
            assertThat(snapshot.status()).isEqualTo("pending");
            assertThat(snapshot.manualAssessmentPresent()).isTrue();
            assertThat(snapshot.activeFindingCount()).isEqualTo(1);
            assertThat(snapshot.findings()).singleElement().satisfies(finding -> {
                assertThat(finding.origin()).isEqualTo("manual");
                assertThat(finding.metric()).isEqualTo("views");
                assertThat(finding.suspicionScore()).isNull();
                assertThat(finding.reviewState()).isEqualTo("unreviewed");
            });
        });

        // A published automatic success exposes its evaluated score; a dismissed
        // review removes the finding from the active set and the public score
        // becomes the evaluated clean zero, never NULL and never the stale 0.9.
        long revision = owner.sql("""
                INSERT INTO analytics.dataset_revision(cause,correlation_id)
                VALUES ('ingestion',gen_random_uuid()) RETURNING id
                """).query(Long.class).single();
        owner.sql("SELECT analytics.rebuild_core_projections(:revision)")
                .param("revision", revision).query().listOfRows();
        assertThat(owner.sql("SELECT id FROM ops_and_admin.pin_latest_anomaly_source_revision()")
                .query(Long.class).single()).isEqualTo(revision);
        UUID token = UUID.randomUUID();
        long generation = owner.sql("""
                INSERT INTO ops_and_admin.anomaly_analysis_candidate(
                    publication_id,eligible_at,claim_token,claimed_generation,leased_until
                ) VALUES (:publication,now(),:token,1,now()+interval '1 minute')
                RETURNING claimed_generation
                """).param("publication", publication).param("token", token).query(Long.class).single();
        owner.sql("""
                SELECT analytics.publish_anomaly_success(
                    :publication,:token,:generation,:attempt,:revision,:hash,:hash,
                    '1.0.0','1.0.0',1,1,now(),'ready',0.9,'high',
                    '[{"metric":"views","detector_id":"delayed_spike_after_plateau","detector_version":"1.0.0",
                       "score":0.9,"severity":"high","explanation_code":"large_rate_jump_after_plateau",
                       "start_at":"2026-09-08T10:00:00Z","end_at":"2026-09-08T10:05:00Z",
                       "start_snapshot_id":"1","end_snapshot_id":"2","evidence":{"rateRatio":12},
                       "quality_codes":[],"alternative_codes":["external_referral"]}]'::jsonb)
                """).param("publication", publication).param("token", token).param("generation", generation)
                .param("attempt", UUID.randomUUID()).param("revision", revision)
                .param("hash", "b".repeat(64)).query(Long.class).single();
        var published = repository.load(publication, 25, null);
        assertThat(published.status()).isEqualTo("ready");
        assertThat(published.suspicionScore()).isEqualByComparingTo("0.9");
        assertThat(published.activeFindingCount()).isEqualTo(2);
        UUID automatic = published.findings().stream()
                .filter(finding -> finding.origin().equals("automatic")).findFirst().orElseThrow().id();
        owner.sql("""
                SELECT analytics.append_anomaly_review(
                    :finding,'dismissed','private',:actor,:correlation,:idempotency,:digest)
                """).param("finding", automatic).param("actor", "jdbc-integration")
                .param("correlation", UUID.randomUUID()).param("idempotency", UUID.randomUUID())
                .param("digest", "c".repeat(64)).query(String.class).single();
        var reviewed = repository.load(publication, 25, null);
        assertThat(reviewed.analysisRevision()).isGreaterThan(published.analysisRevision());
        assertThat(reviewed.suspicionScore()).isEqualByComparingTo("0");
        assertThat(reviewed.activeFindingCount()).isEqualTo(1);
        assertThat(reviewed.manualAssessmentPresent()).isTrue();
        assertThat(reviewed.findings()).allSatisfy(finding -> assertThat(finding.origin()).isEqualTo("manual"));
    }

    private static DriverManagerDataSource dataSource(String url, String username, String password) {
        DriverManagerDataSource dataSource = new DriverManagerDataSource(url, username, password);
        dataSource.setDriverClassName("org.postgresql.Driver");
        return dataSource;
    }

    private static String requiredEnvironment(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException(name + " must be set for the integration test");
        }
        return value;
    }
}
