package org.mranked.query.domain;

import java.util.List;

public record ActivityRatingResult(
        List<ActivityRatingEntity> entities,
        List<ActivityRatingPublication> publications,
        boolean entitiesTruncated
) {
    public ActivityRatingResult {
        entities = List.copyOf(entities);
        publications = List.copyOf(publications);
    }
}
