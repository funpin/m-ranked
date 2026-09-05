package org.mranked.analytics.domain;

import java.math.BigDecimal;
import java.time.Instant;

public record MetricSet(
        BigDecimal totalReactions,
        BigDecimal totalViews,
        BigDecimal medianReactions,
        BigDecimal medianViews,
        int sampleSize,
        BigDecimal coverage,
        String quality,
        Instant asOf,
        long datasetRevision
) {
}
