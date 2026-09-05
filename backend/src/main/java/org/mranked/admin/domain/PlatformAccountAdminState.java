package org.mranked.admin.domain;

import java.time.Instant;
import java.util.UUID;

public record PlatformAccountAdminState(
        UUID accountId,
        String platform,
        boolean enabled,
        long rowVersion,
        Instant updatedAt
) {
}
