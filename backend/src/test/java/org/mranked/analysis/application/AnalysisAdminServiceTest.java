package org.mranked.analysis.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class AnalysisAdminServiceTest {
    @Test
    void canonicalDigestIsStableAcrossEvidenceMapOrder() {
        CapturingPort port = new CapturingPort();
        AnalysisAdminService service = new AnalysisAdminService(port);
        UUID id = UUID.randomUUID();
        UUID correlation = UUID.randomUUID();
        UUID key = UUID.randomUUID();
        service.createManual(id, "views", "low", "operator_context", Instant.EPOCH,
                Instant.EPOCH.plusSeconds(1), Map.of("b", 2, "a", 1), "admin", correlation, key);
        String first = port.digest;
        service.createManual(id, "views", "low", "operator_context", Instant.EPOCH,
                Instant.EPOCH.plusSeconds(1), Map.of("a", 1, "b", 2), "admin", correlation, key);
        assertThat(port.digest).isEqualTo(first).matches("[0-9a-f]{64}");
    }

    @Test
    void rejectsInvalidIntervalsAndOversizedPrivateComments() {
        AnalysisAdminService service = new AnalysisAdminService(new CapturingPort());
        assertThatThrownBy(() -> service.createManual(UUID.randomUUID(), "views", "low", "x",
                Instant.EPOCH, Instant.EPOCH, Map.of(), "admin", UUID.randomUUID(), UUID.randomUUID()))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> service.review(UUID.randomUUID(), "dismissed", "x".repeat(2001),
                "admin", UUID.randomUUID(), UUID.randomUUID())).isInstanceOf(IllegalArgumentException.class);
    }

    private static final class CapturingPort implements AnalysisAdminCommandPort {
        private String digest;
        public AnalysisCommandResult createManual(UUID publicationId, String metric, String severity,
                String explanationCode, Instant startAt, Instant endAt, Map<String, Object> evidence,
                String actor, UUID correlationId, UUID idempotencyKey, String requestDigest) {
            digest = requestDigest;
            return new AnalysisCommandResult(UUID.randomUUID(), null, 1, null);
        }
        public AnalysisCommandResult review(UUID findingId, String decision, String privateComment,
                String actor, UUID correlationId, UUID idempotencyKey, String requestDigest) {
            digest = requestDigest;
            return new AnalysisCommandResult(findingId, UUID.randomUUID(), 1, decision);
        }
    }
}
