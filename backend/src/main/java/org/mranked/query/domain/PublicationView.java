package org.mranked.query.domain;

import java.time.Instant;
import org.mranked.analytics.domain.CounterMetric;
import org.mranked.analytics.domain.Platform;
import org.mranked.ingestion.domain.PublicationIdentity;

public record PublicationView(
        PublicationIdentity publication,
        Platform platform,
        CounterMetric views,
        CounterMetric reactions,
        CounterMetric comments,
        CounterMetric shares,
        String quality,
        boolean intervalUncertain,
        boolean synthetic,
        String historyCompleteness,
        Instant observedAt,
        long datasetRevision
) {
    public PublicationView withFallbackAsOf(Instant fallback) {
        if (observedAt != null) {
            return this;
        }
        return new PublicationView(
                publication, platform, views, reactions, comments, shares, quality,
                intervalUncertain, synthetic, historyCompleteness, fallback, datasetRevision
        );
    }
}
