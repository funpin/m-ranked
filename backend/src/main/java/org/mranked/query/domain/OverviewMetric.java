package org.mranked.query.domain;

import java.math.BigDecimal;

/** Current and previous-window values for one legacy overview counter. */
public record OverviewMetric(
        BigDecimal total,
        BigDecimal median,
        BigDecimal previousTotal,
        BigDecimal previousMedian,
        BigDecimal totalTrend,
        BigDecimal medianTrend
) {
}
