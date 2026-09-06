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
        Instant asOf,
        String nextEntityCursor,
        int entityOffset
) {
    public RatingPage(Platform platform, PeriodKey period, String entityType, String publicationLegacyType,
                      String channelSort, String channelDirection, String postSort, String postDirection,
                      List<ActivityRatingEntity> entities, List<ActivityRatingPublication> publications,
                      int entityLimit, boolean entitiesTruncated, long datasetRevision, Instant asOf) {
        this(platform, period, entityType, publicationLegacyType, channelSort, channelDirection,
                postSort, postDirection, entities, publications, entityLimit, entitiesTruncated,
                datasetRevision, asOf, null, 0);
    }

    public RatingPage {
        entities = List.copyOf(entities);
        publications = List.copyOf(publications);
    }
}
