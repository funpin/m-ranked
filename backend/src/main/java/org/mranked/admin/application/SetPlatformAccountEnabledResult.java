package org.mranked.admin.application;

import org.mranked.admin.domain.PlatformAccountAdminState;

public record SetPlatformAccountEnabledResult(
        SetPlatformAccountEnabledOutcome outcome,
        PlatformAccountAdminState account,
        Long datasetRevision
) {
}
