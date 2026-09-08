package org.mranked.analysis.application;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.mranked.analysis.domain.AnalysisFinding;

public record AnalysisSnapshot(
        UUID publicationId, long analysisRevision, Long sourceDatasetRevision,
        Instant analyzedAt, String status, Instant sourceRevisionAt, BigDecimal suspicionScore,
        String overallSeverity, boolean manualAssessmentPresent, List<String> affectedMetrics,
        int activeFindingCount, List<AnalysisFinding> findings, UUID continuationId
) {
}
