package org.mranked.query.domain;

import org.mranked.analytics.domain.MetricSet;
import org.mranked.analytics.domain.PeriodKey;
import org.mranked.analytics.domain.Platform;
import org.mranked.catalog.domain.InstitutionIdentity;

public record OverviewItem(
        InstitutionIdentity institution,
        Platform platform,
        PeriodKey period,
        MetricSet metrics
) {
}
