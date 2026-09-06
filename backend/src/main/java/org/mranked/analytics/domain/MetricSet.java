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
        long datasetRevision,
        java.util.Map<String, AggregateMetric> aggregates
) {
    public MetricSet(BigDecimal totalReactions, BigDecimal totalViews, BigDecimal medianReactions,
                     BigDecimal medianViews, int sampleSize, BigDecimal coverage, String quality,
                     Instant asOf, long datasetRevision) {
        this(totalReactions, totalViews, medianReactions, medianViews, sampleSize, coverage, quality,
                asOf, datasetRevision, java.util.Map.of());
    }
    public MetricSet { aggregates = java.util.Map.copyOf(aggregates); }
}
