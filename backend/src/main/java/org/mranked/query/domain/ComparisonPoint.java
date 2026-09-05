package org.mranked.query.domain;

import java.math.BigDecimal;

public record ComparisonPoint(
        int hourOffset,
        BigDecimal value,
        int sampleSize,
        BigDecimal coverage,
        String quality
) {
}
