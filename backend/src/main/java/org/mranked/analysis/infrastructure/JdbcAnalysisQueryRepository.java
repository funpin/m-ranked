package org.mranked.analysis.infrastructure;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Types;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.mranked.analysis.application.AnalysisQueryPort;
import org.mranked.analysis.application.AnalysisSnapshot;
import org.mranked.analysis.domain.AnalysisFinding;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

@Repository
public class JdbcAnalysisQueryRepository implements AnalysisQueryPort {
    private static final ObjectMapper JSON = new JsonMapper();
    private static final String LOAD_SQL = """
            WITH page AS (
                SELECT finding.*
                  FROM analytics.publication_anomaly_finding_public finding
                 WHERE finding.publication_id=:publication AND finding.active
                   AND (CAST(:after AS uuid) IS NULL OR finding.id>CAST(:after AS uuid))
                 ORDER BY finding.id LIMIT :fetchLimit
            ), bounded AS (
                SELECT * FROM page ORDER BY id LIMIT :limit
            ), aggregate AS (
                SELECT count(*)::integer AS active_count,
                       bool_or(origin='manual') AS manual_present,
                       max(suspicion_score) FILTER (WHERE origin='automatic') AS automatic_score,
                       array_agg(DISTINCT metric::text ORDER BY metric::text) AS affected_metrics,
                       (array_agg(severity ORDER BY CASE severity WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC))[1] AS overall_severity
                  FROM analytics.publication_anomaly_finding_public
                 WHERE publication_id=:publication AND active
            )
            SELECT publication.id AS publication_id,coalesce(state.analysis_revision_id,0) AS analysis_revision,
                   state.source_dataset_revision_id,state.analyzed_at,coalesce(state.status,'pending') AS status,
                   state.source_revision_at,
                   -- Evaluated result: maximum score of currently active automatic
                   -- findings (dismissed/data_error reviews drop out). NULL stays
                   -- NULL: pending or all-abstained is never rendered as a clean zero.
                   CASE WHEN state.suspicion_score IS NULL THEN NULL
                        ELSE coalesce(aggregate.automatic_score,0) END AS suspicion_score,
                   aggregate.overall_severity,
                   coalesce(aggregate.manual_present,false) AS manual_present,
                   coalesce(aggregate.affected_metrics,ARRAY[]::text[]) AS affected_metrics,
                   coalesce(aggregate.active_count,0) AS active_count,
                   coalesce((SELECT jsonb_agg(jsonb_build_object(
                       'id',id,'origin',origin,'metric',metric,'detectorId',detector_id,'detectorVersion',detector_version,
                       'suspicionScore',suspicion_score,'severity',severity,'explanationCode',explanation_code,
                       'suspiciousStartAt',suspicious_start_at,'suspiciousEndAt',suspicious_end_at,
                       'startSnapshotId',start_snapshot_id,'endSnapshotId',end_snapshot_id,'evidence',evidence,
                       'qualityCodes',quality_codes,'alternativeExplanationCodes',alternative_explanation_codes,
                       'reviewState',review_state) ORDER BY id) FROM bounded),'[]'::jsonb) AS findings,
                   CASE WHEN (SELECT count(*) FROM page)>:limit
                        THEN (SELECT id FROM bounded ORDER BY id DESC LIMIT 1) END AS continuation_id
              FROM ingest.publication publication
              LEFT JOIN analytics.publication_analysis_state_public state ON state.publication_id=publication.id
              CROSS JOIN aggregate
             WHERE publication.id=:publication
            """;

    private final JdbcClient jdbc;

    public JdbcAnalysisQueryRepository(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<UUID> resolvePublication(String id, String legacyType) {
        try {
            UUID uuid = UUID.fromString(id);
            return jdbc.sql("SELECT id FROM ingest.publication WHERE id=:id")
                    .param("id", uuid).query(UUID.class).optional();
        } catch (IllegalArgumentException ignored) {
            if (!id.matches("[0-9]{1,19}") || !(legacyType.equals("posts") || legacyType.equals("platform_posts"))) {
                throw new IllegalArgumentException("invalid publication identity");
            }
            return jdbc.sql("""
                    SELECT target_uuid FROM catalog.legacy_entity_alias
                     WHERE entity_type=:type AND legacy_id=:legacy
                    """).param("type", legacyType).param("legacy", Long.parseLong(id)).query(UUID.class).optional();
        }
    }

    @Override
    public AnalysisSnapshot load(UUID publicationId, int limit, UUID after) {
        int actualLimit = Math.max(0, limit);
        return jdbc.sql(LOAD_SQL).param("publication", publicationId)
                .param("after", after, Types.OTHER).param("limit", actualLimit)
                .param("fetchLimit", actualLimit + 1).query(JdbcAnalysisQueryRepository::map).single();
    }

    private static AnalysisSnapshot map(ResultSet row, int ignored) throws SQLException {
        JsonNode findingsJson = JSON.readTree(row.getString("findings"));
        List<AnalysisFinding> findings = new ArrayList<>();
        for (JsonNode item : findingsJson) {
            Map<String, Object> evidence = JSON.convertValue(item.path("evidence"), new TypeReference<>() {});
            findings.add(new AnalysisFinding(
                    UUID.fromString(item.path("id").asText()), item.path("origin").asText(), item.path("metric").asText(),
                    nullable(item, "detectorId"), nullable(item, "detectorVersion"),
                    item.path("suspicionScore").isNumber() ? item.path("suspicionScore").decimalValue() : null,
                    item.path("severity").asText(), item.path("explanationCode").asText(),
                    Instant.parse(item.path("suspiciousStartAt").asText()), Instant.parse(item.path("suspiciousEndAt").asText()),
                    nullable(item, "startSnapshotId"), nullable(item, "endSnapshotId"), evidence,
                    strings(item.path("qualityCodes")), strings(item.path("alternativeExplanationCodes")),
                    item.path("reviewState").asText()
            ));
        }
        Long sourceRevision = row.getObject("source_dataset_revision_id", Long.class);
        return new AnalysisSnapshot(
                row.getObject("publication_id", UUID.class), row.getLong("analysis_revision"), sourceRevision,
                instant(row, "analyzed_at"), row.getString("status"), instant(row, "source_revision_at"),
                row.getBigDecimal("suspicion_score"), row.getString("overall_severity"), row.getBoolean("manual_present"),
                List.copyOf(java.util.Arrays.asList((String[]) row.getArray("affected_metrics").getArray())),
                row.getInt("active_count"), findings,
                row.getObject("continuation_id", UUID.class)
        );
    }

    private static Instant instant(ResultSet row, String column) throws SQLException {
        OffsetDateTime value = row.getObject(column, OffsetDateTime.class);
        return value == null ? null : value.toInstant();
    }

    private static String nullable(JsonNode item, String field) {
        JsonNode value = item.path(field);
        return value.isMissingNode() || value.isNull() ? null : value.asText();
    }

    private static List<String> strings(JsonNode node) {
        List<String> values = new ArrayList<>();
        node.forEach(value -> values.add(value.asText()));
        return List.copyOf(values);
    }
}
