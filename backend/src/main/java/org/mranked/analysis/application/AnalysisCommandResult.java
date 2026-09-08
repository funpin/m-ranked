package org.mranked.analysis.application;

import java.util.UUID;

public record AnalysisCommandResult(UUID findingId, UUID reviewId, long analysisRevision, String decision) {
}
