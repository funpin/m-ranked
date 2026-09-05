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
        return new InstitutionView(
                institution, platform, period,
                new MetricSet(
                        metrics.totalReactions(), metrics.totalViews(),
                        metrics.medianReactions(), metrics.medianViews(),
                        metrics.sampleSize(), metrics.coverage(), metrics.quality(),
                        fallback, metrics.datasetRevision()
                )
        );
    }
}
