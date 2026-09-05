package org.mranked.query.domain;

import java.time.Instant;
import java.util.UUID;
import org.mranked.analytics.domain.Platform;
import org.mranked.catalog.domain.InstitutionIdentity;
import org.mranked.catalog.domain.LegacyEntityType;

public record AccountView(
        UUID id,
        long legacyId,
        LegacyEntityType legacyEntityType,
        Long channelLegacyId,
        Long platformAccountLegacyId,
        InstitutionIdentity institution,
        Platform platform,
        String canonicalExternalId,
        String username,
        String title,
        String url,
        String accessMode,
        boolean enabled,
        long publicationCount,
        Instant latestObservedAt,
        long datasetRevision,
        Instant asOf
) {
    public AccountView withFallbackAsOf(Instant fallback) {
        if (asOf != null) {
            return this;
        }
        return new AccountView(
                id, legacyId, legacyEntityType, channelLegacyId, platformAccountLegacyId,
                institution, platform, canonicalExternalId,
                username, title, url, accessMode, enabled, publicationCount, latestObservedAt,
                datasetRevision, fallback
        );
    }
}
