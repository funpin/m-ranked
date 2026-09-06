package org.mranked.query.domain;

import java.time.Instant;
import org.mranked.analytics.domain.MetricSet;
import org.mranked.analytics.domain.PeriodKey;
import org.mranked.analytics.domain.Platform;
import org.mranked.catalog.domain.InstitutionIdentity;

public record InstitutionView(
        InstitutionIdentity institution,
        Platform platform,
        PeriodKey period,
        MetricSet metrics
) {
    public InstitutionView withFallbackAsOf(Instant fallback) {
        if (metrics.asOf() != null) {
            return this;
        }
        java.util.Map<String, org.mranked.analytics.domain.AggregateMetric> aggregates = new java.util.LinkedHashMap<>();
        for (String key : java.util.List.of("totalReactions", "totalViews", "medianReactions", "medianViews")) {
            var metric = metrics.aggregates().get(key);
            aggregates.put(key, metric == null
                    ? new org.mranked.analytics.domain.AggregateMetric(null, fallback, metrics.datasetRevision(), 0, null, "unknown")
                    : new org.mranked.analytics.domain.AggregateMetric(metric.value(),
                            metric.asOf() == null ? fallback : metric.asOf(), metric.datasetRevision(),
                            metric.sampleSize(), metric.coverage(), metric.quality()));
        }
        return new InstitutionView(
                institution, platform, period,
                new MetricSet(
                        metrics.totalReactions(), metrics.totalViews(),
                        metrics.medianReactions(), metrics.medianViews(),
                        metrics.sampleSize(), metrics.coverage(), metrics.quality(),
                        fallback, metrics.datasetRevision(), aggregates
                )
        );
    }
}
