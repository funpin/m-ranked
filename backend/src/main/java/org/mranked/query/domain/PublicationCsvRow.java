package org.mranked.query.domain;

import java.time.Instant;
import java.util.UUID;

public record PublicationCsvRow(
        String platform,
        String institution,
        UUID publicationId,
        Instant publishedAt,
        Instant observedAt,
        Long viewsCount,
        Long reactionsCount,
        Long commentsCount,
        Long sharesCount,
        String quality
) {
}
