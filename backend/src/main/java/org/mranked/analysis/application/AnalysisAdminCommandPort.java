package org.mranked.analysis.application;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;

public interface AnalysisAdminCommandPort {
    AnalysisCommandResult createManual(
            UUID publicationId, String metric, String severity, String explanationCode,
            Instant startAt, Instant endAt, Map<String, Object> evidence,
            String actor, UUID correlationId, UUID idempotencyKey, String requestDigest
    );

    AnalysisCommandResult review(
            UUID findingId, String decision, String privateComment, String actor,
            UUID correlationId, UUID idempotencyKey, String requestDigest
    );
}
