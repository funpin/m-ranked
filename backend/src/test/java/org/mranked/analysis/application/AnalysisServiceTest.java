package org.mranked.analysis.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.mranked.analysis.domain.AnalysisFinding;
import org.mranked.cache.domain.DatasetRevision;
import org.mranked.query.application.InvalidCursorException;

class AnalysisServiceTest {
    private static final UUID PUBLICATION = UUID.fromString("10000000-0000-4000-8000-000000000001");
    private static final UUID FINDING = UUID.fromString("80000000-0000-4000-8000-000000000001");

    @Test
    void preservesNullAbstentionAndBuildsRevisionBoundCursor() {
        StubPort port = new StubPort(snapshot(7, null, FINDING));
        var service = new AnalysisService(port, () -> new DatasetRevision(12, Instant.EPOCH));

        var result = service.get(PUBLICATION.toString(), "posts", 25, null);

        assertThat(result.suspicionScore()).isNull();
        assertThat(result.status()).isEqualTo("partial");
        assertThat(result.datasetRevision()).isEqualTo(12);
        assertThat(result.analysisRevision()).isEqualTo(7);
        assertThat(result.nextCursor()).isNotBlank();
        assertThat(port.lastAfter).isNull();
    }

    @Test
    void preservesEvaluatedCleanZero() {
        var result = new AnalysisService(new StubPort(snapshot(8, BigDecimal.ZERO, null)),
                () -> new DatasetRevision(12, Instant.EPOCH))
                .get("1", "posts", 25, null);
        assertThat(result.suspicionScore()).isEqualByComparingTo(BigDecimal.ZERO);
        assertThat(result.status()).isEqualTo("ready");
    }

    @Test
    void rejectsCursorFromAnotherAnalysisRevision() {
        StubPort port = new StubPort(snapshot(9, BigDecimal.ONE, null));
        var service = new AnalysisService(port, () -> new DatasetRevision(12, Instant.EPOCH));
        String old = AnalysisCursor.encode(PUBLICATION, 8, 25, FINDING);
        assertThatThrownBy(() -> service.get(PUBLICATION.toString(), "posts", 25, old))
                .isInstanceOf(InvalidCursorException.class);
    }

    private static AnalysisSnapshot snapshot(long revision, BigDecimal score, UUID continuation) {
        String status = score == null ? "partial" : "ready";
        AnalysisFinding finding = new AnalysisFinding(FINDING, "automatic", "views", "linear_growth",
                "1.0.0", score, "medium", "linear_time_growth", Instant.EPOCH,
                Instant.EPOCH.plusSeconds(60), "1", "2", java.util.Map.of("rSquared", 0.99),
                List.of(), List.of("provider_rounding"), "unreviewed");
        return new AnalysisSnapshot(PUBLICATION, revision, 11L, Instant.EPOCH, status, Instant.EPOCH,
                score, score == null ? null : "medium", false, List.of("views"), 1,
                List.of(finding), continuation);
    }

    private static final class StubPort implements AnalysisQueryPort {
        private final AnalysisSnapshot snapshot;
        private UUID lastAfter;
        private StubPort(AnalysisSnapshot snapshot) { this.snapshot = snapshot; }
        public Optional<UUID> resolvePublication(String id, String type) { return Optional.of(PUBLICATION); }
        public AnalysisSnapshot load(UUID id, int limit, UUID after) { lastAfter = after; return snapshot; }
    }
}
