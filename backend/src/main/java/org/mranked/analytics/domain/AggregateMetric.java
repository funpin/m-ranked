package org.mranked.analytics.domain;

import java.math.BigDecimal;
import java.time.Instant;

/** Value and its own candidate-set metadata; missing is distinct from measured zero. */
public record AggregateMetric(BigDecimal value, Instant asOf, long datasetRevision,
                              int sampleSize, BigDecimal coverage, String quality) {}
