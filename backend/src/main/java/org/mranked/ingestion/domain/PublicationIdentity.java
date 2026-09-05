package org.mranked.ingestion.domain;

import java.time.Instant;
import java.util.UUID;
import org.mranked.catalog.domain.LegacyEntityType;

public record PublicationIdentity(
        UUID id,
        long legacyId,
        LegacyEntityType legacyEntityType,
        UUID institutionId,
        Instant publishedAt,
        String publicationType,
        Instant deletedAt
) {
}
