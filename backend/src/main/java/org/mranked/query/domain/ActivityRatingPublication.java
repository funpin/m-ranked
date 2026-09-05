package org.mranked.query.domain;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

public record ActivityRatingPublication(
        UUID publicationId,
        Long legacyId,
        String legacyType,
        String legacyRoute,
        UUID institutionId,
        long institutionLegacyId,
        String institutionCanonicalName,
        String institutionShortName,
        UUID accountId,
        Long accountLegacyId,
        String accountUsername,
        String accountTitle,
        String externalId,
        String publicUrl,
        Instant publishedAt,
        Instant deletedAt,
        boolean joint,
        int additionalAuthorCount,
        boolean repost,
        Long views,
        Long reactions,
        Long comments,
        Long shares,
        Long interactions,
        BigDecimal subscriberShare,
        BigDecimal viewShare
) {
}
