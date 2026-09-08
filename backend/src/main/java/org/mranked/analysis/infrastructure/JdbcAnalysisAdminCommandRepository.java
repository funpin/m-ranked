package org.mranked.analysis.infrastructure;

import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import org.mranked.analysis.application.AnalysisAdminCommandPort;
import org.mranked.analysis.application.AnalysisCommandResult;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.support.TransactionOperations;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

public class JdbcAnalysisAdminCommandRepository implements AnalysisAdminCommandPort {
    private static final JsonMapper JSON = new JsonMapper();
    private final JdbcClient jdbc;
    private final TransactionOperations transactions;

    public JdbcAnalysisAdminCommandRepository(JdbcClient jdbc, TransactionOperations transactions) {
        this.jdbc = jdbc;
        this.transactions = transactions;
    }

    @Override
    public AnalysisCommandResult createManual(
            UUID publicationId, String metric, String severity, String explanationCode,
            Instant startAt, Instant endAt, Map<String, Object> evidence, String actor,
            UUID correlationId, UUID idempotencyKey, String requestDigest
    ) {
        return Objects.requireNonNull(transactions.execute(status -> {
            String result = jdbc.sql("""
                    SELECT analytics.create_manual_anomaly_signal(
                      :publication,:metric,:severity,:explanation,:startAt,:endAt,
                      CAST(:evidence AS jsonb),:actor,:correlation,:idempotency,:digest)::text
                    """).param("publication", publicationId).param("metric", metric).param("severity", severity)
                    .param("explanation", explanationCode).param("startAt", OffsetDateTime.ofInstant(startAt, java.time.ZoneOffset.UTC))
                    .param("endAt", OffsetDateTime.ofInstant(endAt, java.time.ZoneOffset.UTC))
                    .param("evidence", JSON.writeValueAsString(evidence)).param("actor", actor)
                    .param("correlation", correlationId).param("idempotency", idempotencyKey)
                    .param("digest", requestDigest).query(String.class).single();
            return result(result);
        }));
    }

    @Override
    public AnalysisCommandResult review(
            UUID findingId, String decision, String privateComment, String actor,
            UUID correlationId, UUID idempotencyKey, String requestDigest
    ) {
        return Objects.requireNonNull(transactions.execute(status -> {
            String result = jdbc.sql("""
                    SELECT analytics.append_anomaly_review(
                      :finding,:decision,:comment,:actor,:correlation,:idempotency,:digest)::text
                    """).param("finding", findingId).param("decision", decision).param("comment", privateComment)
                    .param("actor", actor).param("correlation", correlationId).param("idempotency", idempotencyKey)
                    .param("digest", requestDigest).query(String.class).single();
            return result(result);
        }));
    }

    private static AnalysisCommandResult result(String value) {
        JsonNode result = JSON.readTree(value);
        return new AnalysisCommandResult(
                UUID.fromString(result.path("findingId").asText()),
                result.path("reviewId").isMissingNode() || result.path("reviewId").isNull()
                        ? null : UUID.fromString(result.path("reviewId").asText()),
                result.path("analysisRevision").asLong(),
                result.path("decision").isMissingNode() || result.path("decision").isNull()
                        ? null : result.path("decision").asText()
        );
    }
}
