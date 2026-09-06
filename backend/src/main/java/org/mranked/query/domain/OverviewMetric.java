package org.mranked.query.domain;

import java.math.BigDecimal;
import org.mranked.analytics.domain.AggregateMetric;

/** Current and previous-window values for one legacy overview counter. */
public record OverviewMetric(
        BigDecimal total,
        BigDecimal median,
        BigDecimal previousTotal,
        BigDecimal previousMedian,
        BigDecimal totalTrend,
        BigDecimal medianTrend,
        AggregateMetric totalMetadata, AggregateMetric medianMetadata,
        AggregateMetric previousTotalMetadata, AggregateMetric previousMedianMetadata
) {
    public OverviewMetric(BigDecimal total, BigDecimal median, BigDecimal previousTotal,
                          BigDecimal previousMedian, BigDecimal totalTrend, BigDecimal medianTrend) {
        this(total, median, previousTotal, previousMedian, totalTrend, medianTrend, null, null, null, null);
    }
}
