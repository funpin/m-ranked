package org.mranked.admin.application;

import java.util.UUID;

public record SetPlatformAccountEnabledCommand(
        UUID accountId,
        boolean enabled,
        long expectedRowVersion,
        String actor,
        UUID correlationId
) {
}
