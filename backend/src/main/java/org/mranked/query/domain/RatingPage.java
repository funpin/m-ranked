package org.mranked.query.domain;

import java.time.Instant;
import java.util.List;
import org.mranked.analytics.domain.PeriodKey;
import org.mranked.analytics.domain.Platform;

public record RatingPage(
        Platform platform,
        PeriodKey period,
        String entityType,
        String publicationLegacyType,
        String channelSort,
        String channelDirection,
        String postSort,
        String postDirection,
        List<ActivityRatingEntity> entities,
        List<ActivityRatingPublication> publications,
        int entityLimit,
        boolean entitiesTruncated,
        long datasetRevision,
        Instant asOf
) {
    public RatingPage {
        entities = List.copyOf(entities);
        publications = List.copyOf(publications);
    }
}
