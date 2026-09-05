package org.mranked.query.domain;

import java.math.BigDecimal;
import java.util.UUID;

public record ActivityRatingEntity(
        UUID entityId,
        String entityType,
        long legacyId,
        String legacyRoute,
        UUID institutionId,
        Long institutionLegacyId,
        String canonicalName,
        String shortName,
        String username,
        String title,
        int publicationCount,
        BigDecimal averageReactions,
        BigDecimal averageViews,
        long totalReactions,
        Long totalViews,
        Long totalComments,
        Long totalShares,
        Long totalInteractions,
        BigDecimal engagementRate,
        Long subscriberCount
) {
}
