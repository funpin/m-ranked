package org.mranked.query.domain;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.mranked.analytics.domain.PeriodKey;
import org.mranked.analytics.domain.Platform;
import org.mranked.catalog.domain.InstitutionIdentity;

/** Full legacy-card read model; no raw ingestion tables are needed at HTTP time. */
public record OverviewCard(
        UUID entityId,
        String entityType,
        long legacyId,
        String legacyRoute,
        InstitutionIdentity institution,
        Platform platform,
        PeriodKey period,
        List<OverviewAccount> accounts,
        int accountCount,
        int enabledAccountCount,
        int connectedPlatformCount,
        Long subscriberCount,
        Instant lastCheckedAt,
        String lastErrorCode,
        String statusCode,
        Integer ratingRank,
        BigDecimal ratingScore,
        String ratingPeriod,
        Instant ratingFetchedAt,
        Long totalPublicationCount,
        Long activityPublicationCount,
        Long newPublicationCount,
        OverviewMetric views,
        OverviewMetric reactions,
        OverviewMetric comments,
        OverviewMetric shares,
        long datasetRevision,
        Instant asOf
) {
    public OverviewCard {
        accounts = List.copyOf(accounts);
    }

    public OverviewCard withAccounts(List<OverviewAccount> replacementAccounts) {
        return new OverviewCard(
                entityId, entityType, legacyId, legacyRoute, institution,
                platform, period, replacementAccounts, accountCount,
                enabledAccountCount, connectedPlatformCount, subscriberCount,
                lastCheckedAt, lastErrorCode, statusCode, ratingRank,
                ratingScore, ratingPeriod, ratingFetchedAt,
                totalPublicationCount, activityPublicationCount,
                newPublicationCount, views, reactions, comments, shares,
                datasetRevision, asOf
        );
    }
}
