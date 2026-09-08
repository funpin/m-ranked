package org.mranked.analysis.domain;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

public record AnalysisFinding(
        UUID id, String origin, String metric, String detectorId, String detectorVersion,
        BigDecimal suspicionScore, String severity, String explanationCode,
        Instant suspiciousStartAt, Instant suspiciousEndAt,
        String startSnapshotId, String endSnapshotId,
        Map<String, Object> evidence, List<String> qualityCodes,
        List<String> alternativeExplanationCodes, String reviewState
) {
}
