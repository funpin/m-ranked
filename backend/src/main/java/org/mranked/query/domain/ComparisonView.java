package org.mranked.query.domain;

import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.mranked.analytics.domain.Platform;

public record ComparisonView(
        UUID cohortId,
        Platform platform,
        int horizonHours,
        boolean includePartial,
        String metric,
        String aggregation,
        ComparisonSelectionType selectionType,
        int cohortSampleSize,
        List<ComparisonSeries> series,
        long datasetRevision,
        Instant asOf,
        String nextSelectionCursor
) {
    public ComparisonView(UUID cohortId,Platform platform,int horizonHours,boolean includePartial,
                          String metric,String aggregation,ComparisonSelectionType selectionType,
                          int cohortSampleSize,List<ComparisonSeries> series,long datasetRevision,Instant asOf) {
        this(cohortId,platform,horizonHours,includePartial,metric,aggregation,selectionType,
                cohortSampleSize,series,datasetRevision,asOf,null);
    }
    public ComparisonView {
        series = List.copyOf(series);
    }
}
