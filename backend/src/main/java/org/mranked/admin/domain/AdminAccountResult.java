package org.mranked.admin.domain;

import java.time.Instant;
import java.util.UUID;

public record AdminAccountResult(
        long resultId,
        UUID platformAccountId,
        Instant startedAt,
        Instant completedAt,
        String status,
        int discoveredCount,
        int snapshotCount,
        String sanitizedErrorCode
) {
}
