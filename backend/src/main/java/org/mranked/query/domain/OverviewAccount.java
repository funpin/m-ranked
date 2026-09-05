package org.mranked.query.domain;

import java.time.Instant;
import java.util.UUID;
import org.mranked.analytics.domain.Platform;

/** Account metadata frozen into the revision-pinned overview projection. */
public record OverviewAccount(
        UUID id,
        Long legacyId,
        String legacyRoute,
        Platform platform,
        String canonicalExternalId,
        String username,
        String title,
        String url,
        String accessMode,
        boolean enabled,
        Long subscriberCount,
        String subscriberDisplay,
        Instant subscriberObservedAt,
        Instant latestPollStartedAt,
        Instant latestPollCompletedAt,
        String latestPollStatus,
        String latestErrorCode
) {
}
