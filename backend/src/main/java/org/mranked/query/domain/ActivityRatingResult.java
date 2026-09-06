package org.mranked.query.domain;

import java.util.List;

public record ActivityRatingResult(
        List<ActivityRatingEntity> entities,
        List<ActivityRatingPublication> publications,
        boolean entitiesTruncated,
        int entityOffset
) {
    public ActivityRatingResult(List<ActivityRatingEntity> entities, List<ActivityRatingPublication> publications,
                                boolean entitiesTruncated) { this(entities, publications, entitiesTruncated, 0); }
    public ActivityRatingResult {
        entities = List.copyOf(entities);
        publications = List.copyOf(publications);
    }
}
