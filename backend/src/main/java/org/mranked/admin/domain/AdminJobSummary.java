package org.mranked.admin.domain;

import java.time.Instant;
import java.util.UUID;

public record AdminJobSummary(
        UUID jobId,
        String platform,
        Instant scheduledAt,
        Instant startedAt,
        Instant completedAt,
        String status,
        int accountCount,
        int errorCount,
        UUID correlationId
) {
}
