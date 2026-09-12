package org.mranked.analysis.domain;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

public record PublicationAnalysis(
        UUID publicationId, long datasetRevision, long analysisRevision,
        Long sourceDatasetRevision, Instant analyzedAt, String status, Instant sourceRevisionAt,
        BigDecimal suspicionScore, String overallSeverity, boolean manualAssessmentPresent,
        List<String> affectedMetrics, int activeFindingCount, List<AnalysisFinding> findings,
        String nextCursor, String methodologyVersion, String disclaimer
) {
    public static final String METHODOLOGY_VERSION = "anomaly-dynamics-v1";
    public static final String DISCLAIMER = "Сигнал аномальной динамики носит информационный характер и сам по себе не доказывает искусственное происхождение активности или действия университета.";
}
